"""REST API (token login). Not used by the website; kept for a future mobile app.

Login:  POST /api/auth/login/  {"username": "...", "password": "..."}  -> {"token": "..."}
Then send header:  Authorization: Token <token>
"""
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from . import services
from . import notifications
from .models import Attendance, Department, Employee, Holiday, LeaveRequest, Project, Team
from .serializers import (
    AttendanceSerializer, DepartmentSerializer, EmployeeSerializer, LeaveRequestSerializer, ProjectSerializer,
    TeamSerializer,
)


class IsManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return services.is_manager(request.user)


class ManagerWriteOnly(permissions.BasePermission):
    """Everybody logged in can read; only HR/Admin can write."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_authenticated
        return services.is_manager(request.user)


class ProjectWrite(permissions.BasePermission):
    """Everybody logged in can read; writing needs the 'projects' permission (role or designation)."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_authenticated
        return services.can(request.user, "projects")


def _employee_or_400(request):
    emp = services.get_employee(request.user)
    if not emp:
        return None, Response({"detail": "No employee profile linked to this account."}, status=400)
    return emp, None


@api_view(["GET"])
def me(request):
    emp = services.get_employee(request.user)
    return Response(
        {
            "username": request.user.username,
            "name": request.user.get_full_name() or request.user.username,
            "role": services.role_label(request.user),
            "is_manager": services.is_manager(request.user),
            "employee": EmployeeSerializer(emp).data if emp else None,
        }
    )


@api_view(["GET"])
def dashboard(request):
    """Everything the mobile home screen needs in one call."""
    if services.is_manager(request.user):
        return Response(
            {
                "role": services.role_label(request.user),
                "active_employees": Employee.objects.filter(status=Employee.STATUS_ACTIVE).count(),
                "teams": Team.objects.count(),
                "projects_in_progress": Project.objects.filter(status=Project.STATUS_INPROGRESS).count(),
            }
        )
    emp, err = _employee_or_400(request)
    if err:
        return err
    record = services.today_record(emp)
    return Response(
        {
            "role": services.role_label(request.user),
            "department": DepartmentSerializer(emp.department).data if emp.department else None,
            "team": emp.team.name if emp.team else None,
            "designation": emp.designation.name if emp.designation else "",
            "employee_code": emp.employee_id,
            "leave_balance": {k: services.plain(v) for k, v in services.leave_balances(emp)["totals"].items()},
            "holiday_today": services.today_holiday(),
            "today": {
                "date": timezone.localdate(),
                "present": bool(record),
                "in_time": record.in_time if record else None,
                "out_time": record.out_time if record else None,
            },
            "month_summary": services.month_summary(emp),
            "projects_in_progress": ProjectSerializer(
                emp.projects.filter(status=Project.STATUS_INPROGRESS), many=True
            ).data,
        }
    )


@api_view(["POST"])
def clock_in(request):
    emp, err = _employee_or_400(request)
    if err:
        return err
    record, msg, ok = services.clock_in(emp, request.data.get("work_mode", Attendance.MODE_OFFICE))
    return Response({"detail": msg, "attendance": AttendanceSerializer(record).data},
                    status=status.HTTP_200_OK if ok else status.HTTP_409_CONFLICT)


@api_view(["POST"])
def clock_out(request):
    emp, err = _employee_or_400(request)
    if err:
        return err
    record, msg, ok = services.clock_out(emp)
    return Response({"detail": msg, "attendance": AttendanceSerializer(record).data if record else None},
                    status=status.HTTP_200_OK if ok else status.HTTP_409_CONFLICT)


@api_view(["GET"])
def my_attendance(request):
    emp, err = _employee_or_400(request)
    if err:
        return err
    today = timezone.localdate()
    qs = emp.attendance.filter(date__year=today.year, date__month=today.month)
    return Response({
        "summary": services.month_summary(emp),
        "records": AttendanceSerializer(qs, many=True).data,
        "history": services.attendance_history(emp, 30),
    })


@api_view(["GET"])
@permission_classes([IsManager])
def attendance_today(request):
    """HR/Admin: today's in/out time of every active employee (for the app's home table)."""
    records = {a.employee_id: a for a in Attendance.objects.filter(date=timezone.localdate())}
    rows = []
    employees = Employee.objects.select_related("user", "department").filter(status=Employee.STATUS_ACTIVE)
    for emp in employees:
        rec = records.get(emp.id)
        rows.append({
            "id": emp.id,
            "employee_id": emp.employee_id,
            "name": emp.full_name,
            "department": emp.department.name if emp.department else None,
            "present": bool(rec),
            "in_time": rec.in_time if rec else None,
            "out_time": rec.out_time if rec else None,
        })
    return Response(rows)


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related("user", "department", "team")
    serializer_class = EmployeeSerializer
    permission_classes = [IsManager]

    @action(detail=True, methods=["get"])
    def attendance(self, request, pk=None):
        """GET /api/employees/<id>/attendance/ - month summary + last 30 days in/out."""
        emp = self.get_object()
        return Response({
            "employee": emp.full_name,
            "summary": services.month_summary(emp),
            "history": services.attendance_history(emp, 30),
        })

    def perform_destroy(self, instance):
        instance.user.delete()


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [ManagerWriteOnly]


class TeamViewSet(viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = [ManagerWriteOnly]


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [ProjectWrite]

    def get_queryset(self):
        if services.can(self.request.user, "projects"):
            return Project.objects.all()
        emp = services.get_employee(self.request.user)
        return Project.objects.filter(employees=emp) if emp else Project.objects.none()

    def _sync(self, project, is_new):
        modes = {}
        raw = self.request.data.get("work_modes") or {}
        if isinstance(raw, dict):
            modes = {int(k): v for k, v in raw.items() if str(k).isdigit() and v in ("office", "field")}
        added = services.sync_assignments(project, list(project.employees.all()), modes, is_new=is_new)
        if added:
            notifications.notify_project_assigned(project, added, modes, self.request.user)

    def perform_create(self, serializer):
        self._sync(serializer.save(), True)

    def perform_update(self, serializer):
        self._sync(serializer.save(), False)

    @action(detail=True, methods=["post"])
    def update_progress(self, request, pk=None):
        """POST /api/projects/<id>/update_progress/  {"percent": 40, "note": "..."} - the employee's daily update."""
        emp, err = _employee_or_400(request)
        if err:
            return err
        upd, msg, ok = services.submit_project_update(
            emp, self.get_object(), request.data.get("percent"), request.data.get("note", ""))
        return Response({"detail": msg, "percent": upd.percent if upd else None},
                        status=200 if ok else 400)


@api_view(["GET"])
def leave_balance(request):
    emp, err = _employee_or_400(request)
    if err:
        return err
    b = services.leave_balances(emp)
    return Response({
        "year": b["year"], "totals": {k: services.plain(v) for k, v in b["totals"].items()},
        "types": [{"type": r["type"].name, "unlimited": r["unlimited"], "credit": services.plain(r["credit"]),
                   "used": services.plain(r["used"]), "pending": services.plain(r["pending"]),
                   "balance": services.plain(r["balance"])} for r in b["rows"]],
    })


class LeaveViewSet(viewsets.ModelViewSet):
    """Employees: own leave (can apply). Anyone with the 'leave' permission: all leave + approve / reject."""
    serializer_class = LeaveRequestSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related("leave_type")
        if services.can(self.request.user, "leave"):
            return qs
        emp = services.get_employee(self.request.user)
        return qs.filter(employee=emp) if emp else qs.none()

    def perform_create(self, serializer):
        emp = services.get_employee(self.request.user)
        if not emp:
            raise serializers.ValidationError("No employee profile linked to this account.")
        d = serializer.validated_data
        msg = services.validate_leave(emp, d["leave_type"], d["start_date"], d["end_date"],
                                      half_day=bool(d.get("half_day")))
        if msg:
            raise serializers.ValidationError(msg)
        leave = serializer.save(employee=emp)
        notifications.notify_leave_applied(leave, self.request.user)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        if not services.can(request.user, "leave"):
            return Response({"detail": "Not allowed."}, status=403)
        leave = self.get_object()
        decision = request.data.get("action")
        if decision not in ("approve", "reject"):
            return Response({"detail": "action must be approve or reject"}, status=400)
        leave.status = LeaveRequest.STATUS_APPROVED if decision == "approve" else LeaveRequest.STATUS_REJECTED
        leave.decided_by = request.user
        leave.save()
        notifications.notify_leave_decided(leave, request.user)
        return Response(LeaveRequestSerializer(leave).data)


@api_view(["GET"])
def holidays(request):
    """Government / company holidays of a year (?year=2026). 2nd Saturdays and Sundays are automatic."""
    year = int(request.query_params["year"]) if request.query_params.get("year", "").isdigit() \
        else timezone.localdate().year
    return Response([
        {"date": h.date, "name": h.name, "kind": h.kind}
        for h in Holiday.objects.filter(date__year=year)
    ])
