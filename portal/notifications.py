"""In-app notifications + WhatsApp.

WhatsApp works in two ways (set WHATSAPP_MODE in .env):

  link  (default, free, no setup)  - every message is saved as a notification and shows an
                                     "Open WhatsApp" button (wa.me click-to-chat link) with the text already typed.
  cloud (automatic)                - messages are sent by the WhatsApp Business Cloud API (Meta).
                                     Needs WHATSAPP_TOKEN and WHATSAPP_PHONE_ID.  See GUIDE.md.

A failure here never stops the page: the notification is still saved.
"""
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings
from django.db import connection
from django.db.models import Q

from .models import Employee, Notification
from .services import fmt_date, plain

log = logging.getLogger(__name__)


def normalize_phone(raw):
    """'98765 43210' -> '919876543210' (10 digit numbers get the default country code, India = 91)."""
    digits = re.sub(r"\D", "", raw or "")
    country = str(getattr(settings, "WHATSAPP_DEFAULT_COUNTRY", "91"))
    if len(digits) == 10:
        digits = country + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = country + digits[1:]
    return digits if len(digits) >= 11 else ""


def wa_link(phone, text):
    number = normalize_phone(phone)
    return f"https://wa.me/{number}?text={quote(text)}" if number else ""


def cloud_enabled():
    return (
        str(getattr(settings, "WHATSAPP_MODE", "link")).lower() == "cloud"
        and getattr(settings, "WHATSAPP_TOKEN", "")
        and getattr(settings, "WHATSAPP_PHONE_ID", "")
    )


def _send_cloud(notification_id, number, text):
    """Runs in a background thread so the web page is never slowed down."""
    status = Notification.WA_FAILED
    try:
        url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_ID}/messages"
        body = json.dumps({
            "messaging_product": "whatsapp", "to": number, "type": "text", "text": {"body": text},
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}", "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                status = Notification.WA_SENT
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("WhatsApp send failed: %s", exc)
    finally:
        try:
            Notification.objects.filter(pk=notification_id).update(whatsapp=status)
        finally:
            connection.close()


def notify(recipients, message, kind="info", sender=None):
    """Save a notification for each employee (and send it on WhatsApp when cloud mode is on)."""
    created, seen = [], set()
    cloud = cloud_enabled()
    for emp in recipients:
        if not emp or emp.pk in seen:
            continue
        seen.add(emp.pk)
        number = normalize_phone(emp.phone)
        wa = Notification.WA_LINK if number else Notification.WA_NOPHONE
        n = Notification.objects.create(
            recipient=emp, sender=sender if getattr(sender, "pk", None) else None,
            kind=kind, message=message, whatsapp=wa,
        )
        created.append(n)
        if cloud and number:
            threading.Thread(target=_send_cloud, args=(n.pk, number, message), daemon=True).start()
    return created


def leave_approvers():
    """Admin / HR role + everyone whose designation can approve leave."""
    return list(
        Employee.objects.select_related("user", "designation").filter(status=Employee.STATUS_ACTIVE).filter(
            Q(role__in=(Employee.ROLE_ADMIN, Employee.ROLE_HR)) | Q(designation__can_manage_leave=True)
        ).distinct()
    )


def _days_text(leave):
    d = plain(leave.days)
    return f"{d} day{'s' if d != 1 else ''}" + (" (half day)" if leave.half_day else "")


def notify_leave_applied(leave, sender=None):
    emp = leave.employee
    msg = (f"Leave request: {emp.full_name} ({emp.employee_id}) applied {leave.leave_type.name} "
           f"from {fmt_date(leave.start_date)} to {fmt_date(leave.end_date)} - {_days_text(leave)}."
           + (f" Reason: {leave.reason}" if leave.reason else "") + " Please approve or decline in the HR portal.")
    return notify([a for a in leave_approvers() if a.pk != emp.pk], msg, kind="leave", sender=sender)


def notify_leave_decided(leave, sender=None):
    verb = "approved" if leave.status == "approved" else "declined"
    msg = (f"Your {leave.leave_type.name} request ({fmt_date(leave.start_date)} to {fmt_date(leave.end_date)}, "
           f"{_days_text(leave)}) was {verb}.")
    return notify([leave.employee], msg, kind="leave", sender=sender)


def notify_project_assigned(project, employees, modes, assigner=None):
    created = []
    by = (assigner.get_full_name() or assigner.username) if assigner else "HR"
    for emp in employees:
        mode = "Field work" if modes.get(emp.pk) == "field" else "Office work"
        msg = (f"New project assigned: {project.name}. Work type: {mode}. "
               f"Start {fmt_date(project.start_date)}, end {fmt_date(project.end_date) if project.end_date else 'open'}. "
               f"Assigned by {by}. Please update your daily progress in the HR portal.")
        created += notify([emp], msg, kind="project", sender=assigner)
    return created
