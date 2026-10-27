from django.conf import settings

from .models import Notification
from .services import get_employee, get_perms, is_manager, role_label


def portal(request):
    user = request.user
    ctx = {"COMPANY_NAME": settings.COMPANY_NAME, "COMPANY_SHORT": settings.COMPANY_SHORT_NAME}
    if user.is_authenticated:
        emp = get_employee(user)
        # What the sidebar shows under the name: the designation (not "Employee" / "Super Admin").
        designation = emp.designation.name if emp and emp.designation else ""
        ctx.update(
            {
                "is_manager": is_manager(user),
                "my_perms": sorted(get_perms(user)),
                "my_employee": emp,
                "my_role": role_label(user),
                "my_title": designation or ("" if role_label(user) in ("Employee", "Super Admin") else role_label(user)),
                "display_name": user.get_full_name() or user.username,
                "unread_notifications": Notification.objects.filter(recipient=emp, is_read=False).count() if emp else 0,
            }
        )
    return ctx
