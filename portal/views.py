from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import notifications, services
from .forms import (
    AdminLoginForm, AttendanceForm, DepartmentForm, DesignationForm, EmployeeForm, EmployeeLoginForm,
    HolidayForm, LeaveForm, LeaveTypeForm, ProjectForm, TeamForm,
)
from .models import (
    Attendance, Department, Designation, Employee, Holiday, LeaveRequest, LeaveType, Notification, Project,
    ProjectUpdate, Team,
)


# ---------------------------------------------------------------- access control
def _deny(request):
    return render(request, "portal/forbidden.html", status=403)


def perm_required(perm):
    """Designation / role based access: perm is one of employees, projects, leave, attendance."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('admin_login')}?next={request.get_full_path()}")
            if not services.can(request.user, perm):
                return _deny(request)
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def manager_required(view):
    """Admin / HR role only (used for things that hand out permissions)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('admin_login')}?next={request.get_full_path()}")
        if not services.is_manager(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------- login pages
class PortalLoginView(auth_views.LoginView):
    template_name = "portal/login.html"
    redirect_authenticated_user = True
    portal = "employee"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["portal"] = self.portal
        return ctx


employee_login = PortalLoginView.as_view(authentication_form=EmployeeLoginForm, portal="employee")
admin_login = PortalLoginView.as_view(authentication_form=AdminLoginForm, portal="admin")


# ---------------------------------------------------------------- helpers
def _safe_next(request, default):
    """Where to go after a button press: a page name or a path on this site, never another website."""
    nxt = request.POST.get("next") or ""
    if nxt and (nxt in {"dashboard", "leave_list", "holiday_list", "project_list", "notifications"}):
        return nxt
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return default


def _period(request):
    return services.parse_period(request.GET)


def _employee_overview(emp, period):
    """Everything the personal pages show: attendance summary, daily/monthly rows, leave credit, projects."""
    today = timezone.localdate()
    # load the attendance / leave / holidays of the chosen period ONCE and share it
    loaded = services.load_period(emp, period["start"], period["end"])
    record = loaded[0].get(today) if period["start"] <= today <= period["end"] else services.today_record(emp)
    ctx = {"period": period, "emp": emp, "employee": emp, "today": today, "record": record}
    if period["mode"] == "year":
        ctx["breakdown"], ctx["summary"] = services.yearly_breakdown(emp, period["year"], today, loaded)
    else:
        ctx["summary"] = services.period_summary(emp, period["start"], period["end"], today, loaded)
        ctx["history"] = services.attendance_rows(emp, period["start"], period["end"], today, loaded)
    ctx["leave_balance"] = services.leave_balances(emp, period["year"])
    ctx["leaves"] = emp.leaves.select_related("leave_type").filter(
        start_date__lte=period["end"], end_date__gte=period["start"]
    )
    pv = services.employee_project_view(emp, today)
    ctx["projects"] = pv["current"] + pv["completed"]
    ctx["projects_current"] = pv["current"]
    ctx["projects_completed"] = pv["completed"]
    ctx["projects_active"] = pv["current"]
    ctx["project_office_days"] = pv["office_days"]
    ctx["project_field_days"] = pv["field_days"]
    ctx["holiday_today"] = services.today_holiday(today)
    return ctx


# ---------------------------------------------------------------- dashboards
@login_required
def dashboard(request):
    if services.is_manager(request.user):
        return admin_dashboard(request)
    return employee_dashboard(request)


def employee_dashboard(request):
    emp = services.get_employee(request.user)
    period = _period(request)
    if not emp:
        return render(request, "portal/dashboard_employee.html", {"employee": None, "period": period})
    return render(request, "portal/dashboard_employee.html", _employee_overview(emp, period))


def admin_dashboard(request):
    today = timezone.localdate()
    period = _period(request)
    employees = list(Employee.objects.select_related("user", "department", "team", "designation"))
    today_map = {a.employee_id: a for a in Attendance.objects.filter(date=today)}
    leave_ranges = services.load_leave_ranges([e.pk for e in employees])
    on_leave_today = 0
    totals = dict(present=0, leave=0, absent=0, office=0, field=0)
    active = [e for e in employees if e.status == Employee.STATUS_ACTIVE]
    # one batch for everybody (3 queries) instead of 3 queries per employee
    summaries = services.bulk_period_summaries(active, period["start"], period["end"], today, leave_ranges)
    for e in employees:
        e.today = today_map.get(e.id)
        e.on_leave = (not e.today) and bool(services.leave_dates(leave_ranges.get(e.pk), today, today))
        on_leave_today += 1 if e.on_leave else 0
        s = summaries.get(e.pk)
        if s:
            for k in totals:
                totals[k] += s[k]
    projects = list(Project.objects.filter(status=Project.STATUS_INPROGRESS).prefetch_related("employees")[:6])
    pending = LeaveRequest.objects.select_related("employee__user", "leave_type").filter(
        status=LeaveRequest.STATUS_PENDING
    )
    ctx = {
        "employees": employees, "today": today, "period": period, "totals": totals,
        "active_count": sum(1 for e in employees if e.status == Employee.STATUS_ACTIVE),
        "team_count": Team.objects.count(), "present_today": len(today_map), "on_leave_today": on_leave_today,
        "projects_in_progress": Project.objects.filter(status=Project.STATUS_INPROGRESS).count(),
        "project_list": projects, "pending_leaves": pending[:5], "pending_count": pending.count(),
        "holiday_today": services.today_holiday(today),
        "today_company_holiday": Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).first(),
        "today_updates": ProjectUpdate.objects.select_related("project", "employee__user").filter(date=today),
    }
    return render(request, "portal/dashboard_admin.html", ctx)


@login_required
@require_POST
def clock_in(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
    else:
        _, msg, ok = services.clock_in(emp, request.POST.get("work_mode", Attendance.MODE_OFFICE))
        (messages.success if ok else messages.warning)(request, msg)
    return redirect("dashboard")


@login_required
@require_POST
def clock_out(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
    else:
        _, msg, ok = services.clock_out(emp)
        (messages.success if ok else messages.warning)(request, msg)
    return redirect("dashboard")


# ---------------------------------------------------------------- employees
@perm_required("employees")
def employee_list(request):
    q = request.GET.get("q", "").strip()
    employees = Employee.objects.select_related("user", "department", "team", "designation")
    if q:
        employees = employees.filter(
            Q(employee_id__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
            | Q(designation__name__icontains=q)
            | Q(department__name__icontains=q)
            | Q(team__name__icontains=q)
        )
    employees = list(employees)
    percents = services.month_percent_map(employees)
    for e in employees:
        e.month_percent = percents.get(e.pk, 0)
    return render(request, "portal/employee_list.html", {
        "employees": employees, "q": q, "month_label": timezone.localdate().strftime("%B %Y"),
    })


@login_required
def my_profile(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
        return redirect("dashboard")
    ctx = _employee_overview(emp, _period(request))
    ctx.update(back="dashboard", is_self=True)
    return render(request, "portal/employee_detail.html", ctx)


@login_required
def employee_detail(request, pk):
    me = services.get_employee(request.user)
    emp = get_object_or_404(Employee.objects.select_related("user", "department", "team", "designation"), pk=pk)
    is_self = bool(me and me.pk == emp.pk)
    if not (is_self or services.can(request.user, "employees")):
        return _deny(request)
    ctx = _employee_overview(emp, _period(request))
    ctx.update(back="dashboard" if (is_self or request.GET.get("from") == "home") else "employee_list", is_self=is_self)
    return render(request, "portal/employee_detail.html", ctx)


def _may_touch(request, emp):
    """Only Admin / HR may change Admin / HR accounts."""
    return emp.role == Employee.ROLE_EMPLOYEE or services.is_manager(request.user)


@perm_required("employees")
def employee_create(request):
    form = EmployeeForm(request.POST or None, can_set_role=services.is_manager(request.user))
    if request.method == "POST" and form.is_valid():
        emp = form.save()
        messages.success(request, f"Employee {emp.full_name} added with code {emp.employee_id}.")
        return redirect("employee_list")
    return render(request, "portal/form.html", {"form": form, "title": "Add Employee", "back": "employee_list"})


@perm_required("employees")
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not _may_touch(request, emp):
        return _deny(request)
    form = EmployeeForm(request.POST or None, instance=emp, can_set_role=services.is_manager(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Employee updated.")
        return redirect("employee_list")
    return render(request, "portal/form.html", {"form": form, "title": f"Edit Employee - {emp.full_name}", "back": "employee_list"})


@perm_required("employees")
def employee_delete(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not _may_touch(request, emp):
        return _deny(request)
    if emp.user_id == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect("employee_list")
    if request.method == "POST":
        name = emp.full_name
        emp.user.delete()  # cascades to Employee
        messages.success(request, f"Employee {name} deleted.")
        return redirect("employee_list")
    return render(request, "portal/confirm_delete.html", {"object": emp, "back": "employee_list", "what": "employee"})


# ---------------------------------------------------------------- generic add / edit / delete
def _save_form(request, form_class, title, back, instance=None, ok_msg="Saved.", **form_kwargs):
    form = form_class(request.POST or None, instance=instance, **form_kwargs)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, ok_msg)
        return obj, None
    return None, render(request, "portal/form.html", {"form": form, "title": title, "back": back})


def _delete(request, obj, back, what, ok_msg, warning=""):
    if request.method == "POST":
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, f"This {what} is still in use and cannot be deleted.")
            return redirect(back)
        messages.success(request, ok_msg)
        return redirect(back)
    return render(request, "portal/confirm_delete.html", {"object": obj, "back": back, "what": what, "warning": warning})


# ---------------------------------------------------------------- organization (departments, teams, designations, leave types)
@perm_required("employees")
def organization(request):
    departments = Department.objects.annotate(
        emp_count=Count("employees", distinct=True), team_count=Count("teams", distinct=True)
    )
    teams = Team.objects.select_related("department").annotate(member_count=Count("employees", distinct=True))
    designations = Designation.objects.annotate(emp_count=Count("employees", distinct=True))
    return render(request, "portal/organization.html", {
        "departments": departments, "teams": teams, "designations": designations,
        "leave_types": LeaveType.objects.all(),
    })


@perm_required("employees")
def department_create(request):
    obj, resp = _save_form(request, DepartmentForm, "Add Department", "organization", ok_msg="Department created.")
    return redirect("organization") if obj else resp


@perm_required("employees")
def department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    obj, resp = _save_form(request, DepartmentForm, f"Edit Department - {dept.name}", "organization", dept, "Department updated.")
    return redirect("organization") if obj else resp


@perm_required("employees")
def department_delete(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    warning = (
        f"{dept.teams.count()} team(s) in this department will be deleted too, and "
        f"{dept.employees.count()} employee(s) will be left without a department/team. Employees themselves are not deleted."
    )
    return _delete(request, dept, "organization", "department", f"Department {dept.name} deleted.", warning)


@perm_required("employees")
def team_create(request):
    initial = {}
    if request.GET.get("department", "").isdigit():
        initial["department"] = int(request.GET["department"])
    form = TeamForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        team = form.save()
        messages.success(request, f"Team {team.name} created in {team.department.name}.")
        return redirect("organization")
    return render(request, "portal/form.html", {"form": form, "title": "Add Team", "back": "organization"})


@perm_required("employees")
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)
    obj, resp = _save_form(request, TeamForm, f"Edit Team - {team.name}", "organization", team, "Team updated.")
    return redirect("organization") if obj else resp


@perm_required("employees")
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)
    warning = f"{team.employees.count()} employee(s) will be left without a team. Employees themselves are not deleted."
    return _delete(request, team, "organization", "team", f"Team {team.name} deleted.", warning)


@manager_required
def designation_create(request):
    obj, resp = _save_form(request, DesignationForm, "Add Designation", "organization", ok_msg="Designation created.")
    return redirect("organization") if obj else resp


@manager_required
def designation_edit(request, pk):
    d = get_object_or_404(Designation, pk=pk)
    obj, resp = _save_form(request, DesignationForm, f"Edit Designation - {d.name}", "organization", d, "Designation updated.")
    return redirect("organization") if obj else resp


@manager_required
def designation_delete(request, pk):
    d = get_object_or_404(Designation, pk=pk)
    warning = f"{d.employees.count()} employee(s) have this designation; they will be left without one."
    return _delete(request, d, "organization", "designation", f"Designation {d.name} deleted.", warning)


@manager_required
def leavetype_create(request):
    obj, resp = _save_form(request, LeaveTypeForm, "Add Leave Type", "organization", ok_msg="Leave type created.")
    return redirect("organization") if obj else resp


@manager_required
def leavetype_edit(request, pk):
    t = get_object_or_404(LeaveType, pk=pk)
    obj, resp = _save_form(request, LeaveTypeForm, f"Edit Leave Type - {t.name}", "organization", t, "Leave type updated.")
    return redirect("organization") if obj else resp


@manager_required
def leavetype_delete(request, pk):
    t = get_object_or_404(LeaveType, pk=pk)
    return _delete(request, t, "organization", "leave type", f"Leave type {t.name} deleted.",
                   "Leave types that already have leave requests cannot be deleted.")


# ---------------------------------------------------------------- projects
def _project_scope(request):
    if services.can(request.user, "projects"):
        return Project.objects.all()
    emp = services.get_employee(request.user)
    return Project.objects.filter(employees=emp) if emp else Project.objects.none()


@login_required
def project_list(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "projects")
    mine = services.employee_project_view(me) if me else None
    if mine and not (mine["current"] or mine["completed"]):
        mine = None if manage else mine
    projects, q, status = [], "", ""
    period = _period(request)
    filtered = False
    if manage:
        projects = _project_scope(request).prefetch_related("employees__user", "assignments", "updates")
        q = request.GET.get("q", "").strip()
        if q:
            projects = projects.filter(Q(name__icontains=q) | Q(employees__user__first_name__icontains=q)
                                       | Q(employees__employee_id__icontains=q)).distinct()
        status = request.GET.get("status", "")
        if status in dict(Project.STATUS_CHOICES):
            projects = projects.filter(status=status)
        filtered = request.GET.get("period") in ("month", "year")
        period["sel"] = period["mode"] if filtered else "all"
        if filtered:  # projects that were running at some point inside the chosen month / year
            projects = projects.filter(Q(start_date__isnull=True) | Q(start_date__lte=period["end"])).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=period["start"])
            )
        projects = list(projects)
        leave_map = services.load_leave_ranges({e.pk for p in projects for e in p.employees.all()})
        for p in projects:
            p.metrics = services.project_metrics(p, leave_map)
    return render(request, "portal/project_list.html", {
        "projects": projects, "status": status, "q": q, "status_choices": Project.STATUS_CHOICES,
        "period": period, "period_on": filtered, "manage": manage, "mine": mine,
        "today": timezone.localdate(),
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(
        _project_scope(request).prefetch_related("employees__user", "assignments", "updates__employee__user"), pk=pk)
    me = services.get_employee(request.user)
    today = timezone.localdate()
    mine = project.assignments.filter(employee=me).first() if me else None
    my_today = project.updates.filter(employee=me, date=today).first() if me else None
    my_latest = project.updates.filter(employee=me).first() if me else None
    return render(request, "portal/project_detail.html", {
        "project": project, "m": services.project_metrics(project),
        "updates": project.updates.select_related("employee__user")[:60],
        "can_update": bool(mine) and project.status != Project.STATUS_COMPLETED,
        "my_today": my_today, "my_latest": my_latest, "today": today,
    })


@login_required
@require_POST
def project_update(request, pk):
    """Employee's daily progress: how much of the project is finished."""
    project = get_object_or_404(Project, pk=pk)
    emp = services.get_employee(request.user)
    if not emp:
        return _deny(request)
    _, msg, ok = services.submit_project_update(emp, project, request.POST.get("percent"), request.POST.get("note", ""))
    (messages.success if ok else messages.error)(request, msg)
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt in ("dashboard", "project_list") else reverse("project_detail", args=[project.pk]))


def _project_form(request, instance=None):
    form = ProjectForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        added = getattr(form, "added", [])
        if added:
            notifications.notify_project_assigned(project, added, form.modes, request.user)
            if notifications.cloud_enabled():
                messages.success(request, f"Project saved. {len(added)} employee(s) notified on WhatsApp.")
            else:
                messages.success(request, f"Project saved. Tap 'Open WhatsApp' below to message the "
                                          f"{len(added)} assigned employee(s).")
                return redirect("notifications")
        else:
            messages.success(request, "Project saved.")
        return redirect("project_list")
    title = f"Edit Project - {instance.name}" if instance else "Add Project"
    return render(request, "portal/project_form.html", {"form": form, "title": title, "back": "project_list"})


@perm_required("projects")
def project_create(request):
    return _project_form(request)


@perm_required("projects")
def project_edit(request, pk):
    return _project_form(request, get_object_or_404(Project, pk=pk))


@perm_required("projects")
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    return _delete(request, project, "project_list", "project", "Project deleted.")


# ---------------------------------------------------------------- leave
@login_required
def leave_list(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "leave")
    period = _period(request)
    qs = LeaveRequest.objects.select_related("employee__user", "leave_type", "decided_by")
    if not manage:
        qs = qs.filter(employee=me) if me else qs.none()
    q = request.GET.get("q", "").strip()
    if manage and q:
        qs = qs.filter(Q(employee__employee_id__icontains=q) | Q(employee__user__first_name__icontains=q)
                       | Q(employee__user__last_name__icontains=q))
    status = request.GET.get("status", "")
    if status in dict(LeaveRequest.STATUS_CHOICES):
        qs = qs.filter(status=status)
    qs = qs.filter(start_date__lte=period["end"], end_date__gte=period["start"])
    ctx = {
        "leaves": qs, "manage": manage, "period": period, "status": status, "q": q,
        "status_choices": LeaveRequest.STATUS_CHOICES,
        "balance": services.leave_balances(me, period["year"]) if me else None,
        "me": me,
        "overview": services.leave_overview(period["year"]) if manage else None,
    }
    return render(request, "portal/leave_list.html", ctx)


@login_required
def leave_create(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "leave")
    if not me and not manage:
        messages.error(request, "No employee profile is linked to this account.")
        return redirect("dashboard")
    form = LeaveForm(request.POST or None, employee=me, pick_employee=manage)
    if request.method == "POST" and form.is_valid():
        leave = form.save(commit=False)
        if manage:  # HR records leave for someone: it is approved straight away
            leave.status = LeaveRequest.STATUS_APPROVED
            leave.decided_by = request.user
        else:
            leave.employee = me
        leave.save()
        if manage:
            notifications.notify_leave_decided(leave, request.user)
            messages.success(request, f"Leave saved ({services.plain(leave.days)} working day(s)).")
        else:
            notifications.notify_leave_applied(leave, request.user)
            messages.success(request, f"Leave request sent ({services.plain(leave.days)} day(s)). "
                                      "HR / managers have been notified for approval.")
        return redirect("leave_list")
    return render(request, "portal/form.html", {
        "form": form, "title": "Apply Leave", "back": "leave_list",
        "leave_balance": services.leave_balances(me) if me else None,
        "leave_note": "Casual Leave: 1.5 days are credited every month. When the CL credit is finished, "
                      "choose Loss of Pay (LOP). Sundays, 2nd Saturdays and holidays are not counted.",
    })


def _leave_editable(request, leave):
    me = services.get_employee(request.user)
    if services.can(request.user, "leave"):
        return True
    return bool(me and leave.employee_id == me.pk and leave.status == LeaveRequest.STATUS_PENDING)


@login_required
def leave_edit(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not _leave_editable(request, leave):
        return _deny(request)
    manage = services.can(request.user, "leave")
    form = LeaveForm(request.POST or None, instance=leave, employee=leave.employee, pick_employee=manage)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Leave updated.")
        return redirect("leave_list")
    return render(request, "portal/form.html", {
        "form": form, "title": "Edit Leave", "back": "leave_list",
        "leave_balance": services.leave_balances(leave.employee),
    })


@login_required
def leave_delete(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not _leave_editable(request, leave):
        return _deny(request)
    return _delete(request, leave, "leave_list", "leave request", "Leave deleted.")


@perm_required("leave")
@require_POST
def leave_decide(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    action = request.POST.get("action")
    if action == "approve":
        msg = services.validate_leave(leave.employee, leave.leave_type, leave.start_date, leave.end_date,
                                      exclude_pk=leave.pk, half_day=leave.half_day)
        if msg and "credit" in msg:
            messages.error(request, msg)
            return redirect("leave_list")
        leave.status = LeaveRequest.STATUS_APPROVED
    elif action == "reject":
        leave.status = LeaveRequest.STATUS_REJECTED
    else:
        return redirect("leave_list")
    leave.decided_by = request.user
    leave.save()
    notifications.notify_leave_decided(leave, request.user)
    messages.success(request, "Leave approved." if leave.status == LeaveRequest.STATUS_APPROVED else "Leave declined.")
    return redirect(_safe_next(request, "leave_list"))


# ---------------------------------------------------------------- attendance (HR / designation based)
@perm_required("attendance")
def attendance_list(request):
    today = timezone.localdate()
    period = _period(request)
    q = request.GET.get("q", "").strip()
    emps = Employee.objects.select_related("user", "designation").filter(status=Employee.STATUS_ACTIVE)
    if q:
        emps = emps.filter(Q(employee_id__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
    emps = list(emps)
    summaries = services.bulk_period_summaries(emps, period["start"], period["end"], today)
    summary_rows = []
    for e in emps:
        s = dict(summaries[e.pk])
        s["employee"] = e
        summary_rows.append(s)
    records = Attendance.objects.select_related("employee__user").filter(
        date__range=(period["start"], period["end"]), employee_id__in=[e.pk for e in emps]
    )[:150]
    return render(request, "portal/attendance_list.html", {
        "period": period, "q": q, "summary_rows": summary_rows, "records": records,
    })


@perm_required("attendance")
def attendance_create(request):
    obj, resp = _save_form(request, AttendanceForm, "Add Attendance", "attendance_list", ok_msg="Attendance saved.")
    return redirect("attendance_list") if obj else resp


@perm_required("attendance")
def attendance_edit(request, pk):
    rec = get_object_or_404(Attendance, pk=pk)
    obj, resp = _save_form(request, AttendanceForm, f"Edit Attendance - {rec.employee.employee_id} {rec.date:%d-%b-%Y}",
                           "attendance_list", rec, "Attendance updated.")
    return redirect("attendance_list") if obj else resp


@perm_required("attendance")
def attendance_delete(request, pk):
    rec = get_object_or_404(Attendance, pk=pk)
    return _delete(request, rec, "attendance_list", "attendance record", "Attendance record deleted.")


# ---------------------------------------------------------------- holidays
@login_required
def holiday_list(request):
    today = timezone.localdate()
    year = int(request.GET["year"]) if request.GET.get("year", "").isdigit() else today.year
    holidays = list(Holiday.objects.filter(date__year=year))
    second_saturdays = [
        d for d in services.daterange(date(year, 1, 1), date(year, 12, 31)) if services.is_second_saturday(d)
    ]
    return render(request, "portal/holiday_list.html", {
        "holidays": holidays, "year": year, "years": list(range(today.year + 1, today.year - 3, -1)),
        "second_saturdays": second_saturdays, "today": today,
        "today_holiday": services.today_holiday(today),
        "today_company_holiday": Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).first(),
    })


@manager_required
def holiday_create(request):
    form = HolidayForm(request.POST or None, initial={"kind": Holiday.KIND_GOVT})
    if request.method == "POST" and form.is_valid():
        h = form.save(commit=False)
        h.created_by = request.user
        h.save()
        messages.success(request, f"Holiday added: {h.name} ({services.fmt_date(h.date)}).")
        return redirect("holiday_list")
    return render(request, "portal/form.html", {"form": form, "title": "Add Holiday", "back": "holiday_list"})


@manager_required
def holiday_delete(request, pk):
    h = get_object_or_404(Holiday, pk=pk)
    return _delete(request, h, "holiday_list", "holiday", "Holiday removed.")


@manager_required
@require_POST
def holiday_today(request):
    """Admin / HR: declare today as a company holiday (or cancel it)."""
    today = timezone.localdate()
    if request.POST.get("action") == "cancel":
        Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).delete()
        messages.success(request, "Today's company holiday was cancelled.")
    else:
        name = (request.POST.get("name") or "").strip()[:120] or "Company holiday"
        Holiday.objects.update_or_create(
            date=today, defaults={"name": name, "kind": Holiday.KIND_COMPANY, "created_by": request.user})
        messages.success(request, f"Today ({services.fmt_date(today)}) is now a company holiday: {name}.")
    return redirect(_safe_next(request, "dashboard"))


# ---------------------------------------------------------------- notifications (in-app + WhatsApp)
@login_required
def notification_list(request):
    me = services.get_employee(request.user)
    mine = list(Notification.objects.filter(recipient=me)[:50]) if me else []
    outbox = list(
        Notification.objects.select_related("recipient__user").filter(sender=request.user)
        .exclude(whatsapp=Notification.WA_SENT)[:50]
    )
    for n in outbox:
        n.link = notifications.wa_link(n.recipient.phone, n.message)
    if me:
        Notification.objects.filter(recipient=me, is_read=False).update(is_read=True)
    return render(request, "portal/notifications.html", {
        "mine": mine, "outbox": outbox, "cloud": notifications.cloud_enabled(),
    })


@login_required
@require_POST
def notification_sent(request, pk):
    n = get_object_or_404(Notification, pk=pk, sender=request.user)
    n.whatsapp = Notification.WA_SENT
    n.save(update_fields=["whatsapp"])
    return redirect("notifications")
