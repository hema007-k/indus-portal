import re
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, help_text="Short description shown on the employee home page")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="teams")

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "department")

    def __str__(self):
        return self.name


class Designation(models.Model):
    """Job title. The permission flags give designation-based access (on top of the Employee role)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True, help_text="Shown in the employee's personal information")
    can_manage_employees = models.BooleanField(default=False, help_text="Add / edit employees, departments and teams")
    can_manage_projects = models.BooleanField(default=False, help_text="Add / edit projects and assign employees")
    can_manage_leave = models.BooleanField(default=False, help_text="Approve / reject / edit leave")
    can_manage_attendance = models.BooleanField(default=False, help_text="Add / edit attendance records")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def next_employee_code(prefix="EMP", width=3):
    """EMP001, EMP002 ... always one more than the highest existing code."""
    highest = 0
    for code in Employee.objects.values_list("employee_id", flat=True):
        m = re.fullmatch(rf"{prefix}(\d+)", code or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


class Employee(models.Model):
    ROLE_EMPLOYEE = "employee"
    ROLE_HR = "hr"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Employee"),
        (ROLE_HR, "HR"),
        (ROLE_ADMIN, "Super Admin"),
    ]
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_INACTIVE, "Inactive")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee")
    employee_id = models.CharField("Employee Code", max_length=20, unique=True, blank=True,
                                   help_text="Unique code. Leave blank to auto-generate (EMP001, EMP002 ...)")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    designation = models.ForeignKey(Designation, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    joining_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_EMPLOYEE)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["employee_id"]

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def is_manager(self):
        return self.role in (self.ROLE_HR, self.ROLE_ADMIN)

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = next_employee_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee_id} - {self.full_name}"


class Attendance(models.Model):
    MODE_OFFICE = "office"
    MODE_FIELD = "field"
    MODE_CHOICES = [(MODE_OFFICE, "Office"), (MODE_FIELD, "Field")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    in_time = models.TimeField(null=True, blank=True)
    out_time = models.TimeField(null=True, blank=True)
    work_mode = models.CharField(max_length=6, choices=MODE_CHOICES, default=MODE_OFFICE)

    class Meta:
        ordering = ["-date"]
        unique_together = ("employee", "date")

    def __str__(self):
        return f"{self.employee.employee_id} {self.date}"


class Project(models.Model):
    STATUS_INPROGRESS = "inprogress"
    STATUS_COMPLETED = "completed"
    STATUS_ONHOLD = "onhold"
    STATUS_CHOICES = [
        (STATUS_INPROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ONHOLD, "On Hold"),
    ]

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_INPROGRESS)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    completion = models.PositiveSmallIntegerField(
        "Completion %", default=0, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="0 - 100. Setting 100 marks the project as completed.",
    )
    employees = models.ManyToManyField(Employee, blank=True, related_name="projects")

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name


class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    annual_credit = models.PositiveSmallIntegerField(default=12, help_text="Leave days credited to every employee per year")
    monthly_credit = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal("0"),
        help_text="Days credited every month (e.g. 1.5 for Casual Leave). 0 = use the yearly credit instead",
    )
    is_lop = models.BooleanField(
        "Loss of Pay (unlimited)", default=False,
        help_text="Loss of Pay has no credit limit - used when the Casual Leave credit is finished",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_APPROVED, "Approved"), (STATUS_REJECTED, "Rejected")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leaves")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    half_day = models.BooleanField(default=False, help_text="Half day (single date only)")
    days = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0"),
                               help_text="Working days (holidays excluded) - calculated automatically")
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def save(self, *args, **kwargs):
        from .services import leave_days_for

        self.days = leave_days_for(self.start_date, self.end_date, self.half_day)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.employee_id} {self.leave_type} {self.start_date}..{self.end_date}"


class Holiday(models.Model):
    """Government / company holidays. 2nd Saturdays and Sundays are handled in code (services.off_reason)."""

    KIND_GOVT = "government"
    KIND_COMPANY = "company"
    KIND_CHOICES = [(KIND_GOVT, "Government holiday"), (KIND_COMPANY, "Company holiday")]

    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_GOVT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.name}"


class ProjectAssignment(models.Model):
    """One row per (project, employee): whether the person works in the office or in the field."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="assignments")
    work_mode = models.CharField(max_length=6, choices=Attendance.MODE_CHOICES, default=Attendance.MODE_OFFICE)
    assigned_on = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ("project", "employee")

    def __str__(self):
        return f"{self.project} - {self.employee.employee_id} ({self.work_mode})"


class ProjectUpdate(models.Model):
    """Daily progress an employee reports for a project (cumulative % of their part)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="project_updates")
    date = models.DateField()
    percent = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    note = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        unique_together = ("project", "employee", "date")

    def __str__(self):
        return f"{self.project} {self.employee.employee_id} {self.date} {self.percent}%"


class Notification(models.Model):
    """In-app message + WhatsApp status (link = click-to-chat link, sent = sent by WhatsApp Cloud API)."""

    WA_LINK = "link"
    WA_SENT = "sent"
    WA_FAILED = "failed"
    WA_NOPHONE = "nophone"

    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="notifications")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=20, default="info")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    whatsapp = models.CharField(max_length=10, default=WA_LINK)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"to {self.recipient.employee_id}: {self.message[:40]}"
