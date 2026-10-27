from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q as models_q

from . import services
from .models import (
    Attendance, Department, Designation, Employee, Holiday, LeaveRequest, LeaveType, Project, Team,
)

User = get_user_model()


class BootstrapMixin:
    def _style(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"


class EmployeeForm(BootstrapMixin, forms.ModelForm):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Required for a new employee. Leave blank on edit to keep the current password.",
    )
    joining_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = Employee
        fields = ["employee_id", "department", "team", "designation", "joining_date", "status", "role", "phone"]

    field_order = [
        "employee_id", "username", "first_name", "last_name", "email", "password",
        "department", "team", "designation", "joining_date", "status", "role", "phone",
    ]

    def __init__(self, *args, can_set_role=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["designation"].empty_label = "Select designation"
        self.fields["phone"].label = "WhatsApp / mobile number"
        self.fields["phone"].widget.attrs["placeholder"] = "10 digit number, e.g. 9876543210"
        self.fields["employee_id"].widget.attrs["placeholder"] = "Auto (EMP001, EMP002 ...)"
        if not can_set_role:  # only Admin / HR may hand out the Admin / HR role
            self.fields["role"].choices = [c for c in Employee.ROLE_CHOICES if c[0] == Employee.ROLE_EMPLOYEE]
        if self.instance and self.instance.pk:
            u = self.instance.user
            self.fields["username"].initial = u.username
            self.fields["first_name"].initial = u.first_name
            self.fields["last_name"].initial = u.last_name
            self.fields["email"].initial = u.email
        self.fields["team"].label_from_instance = lambda t: f"{t.name} ({t.department.name})"
        self.fields["team"].queryset = Team.objects.select_related("department")
        self._style()

    def clean_employee_id(self):
        code = (self.cleaned_data.get("employee_id") or "").strip().upper()
        if not code and self.instance and self.instance.pk:
            return self.instance.employee_id  # never blank out an existing code
        if code and Employee.objects.filter(employee_id__iexact=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This employee code is already used by another employee.")
        return code

    def clean_username(self):
        username = self.cleaned_data["username"]
        qs = User.objects.filter(username__iexact=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        data = super().clean()
        if not (self.instance and self.instance.pk) and not data.get("password"):
            self.add_error("password", "Password is required for a new employee.")
        dept, team = data.get("department"), data.get("team")
        if dept and team and team.department_id != dept.pk:
            self.add_error("team", f"Team '{team.name}' belongs to {team.department.name}, not {dept.name}.")
        return data

    def save(self, commit=True):
        emp = super().save(commit=False)
        d = self.cleaned_data
        user = emp.user if emp.pk else User()
        user.username = d["username"]
        user.first_name = d["first_name"]
        user.last_name = d.get("last_name", "")
        user.email = d.get("email", "")
        user.is_active = d["status"] == Employee.STATUS_ACTIVE
        if d.get("password"):
            user.set_password(d["password"])
        user.save()
        emp.user = user
        if commit:
            emp.save()
        return emp


class ProjectForm(BootstrapMixin, forms.ModelForm):
    """Add / edit a project: one or more members, and for every member Office or Field work."""

    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        label="Members", help_text="Tick one or more employees and choose Office or Field work for each.",
    )

    class Meta:
        model = Project
        fields = ["name", "description", "status", "completion", "start_date", "end_date", "employees"]
        labels = {"completion": "Completion % (automatic from daily updates)"}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "completion": forms.NumberInput(attrs={"min": 0, "max": 100}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        related = ("user", "designation", "department", "team")
        qs = Employee.objects.select_related(*related).filter(status=Employee.STATUS_ACTIVE)
        if self.instance.pk:  # keep already-assigned (even inactive) people visible
            qs = Employee.objects.select_related(*related).filter(
                models_q(status=Employee.STATUS_ACTIVE) | models_q(projects=self.instance)
            ).distinct()
        self.fields["employees"].queryset = qs
        self.fields["employees"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        current = {}
        if self.instance.pk:
            current = {a.employee_id: a.work_mode for a in self.instance.assignments.all()}
        self._members = list(qs)   # evaluated once; the form, the picker and clean() all reuse it
        for e in self._members:
            self.fields[f"mode_{e.pk}"] = forms.ChoiceField(
                required=False, label="Work type",
                choices=[("", "-- choose --")] + list(Attendance.MODE_CHOICES), initial=current.get(e.pk, ""),
            )
        self._style()

    def members(self):
        """Rows for the member table: checkbox + Office/Field select for each employee."""
        boxes = {str(b.data["value"]): b for b in self["employees"]}
        for e in self._members:
            search = " ".join(filter(None, [
                e.employee_id, e.full_name, e.user.username,
                e.designation.name if e.designation else "", e.department.name if e.department else "",
                e.team.name if e.team else "",
            ]))
            yield {"employee": e, "checkbox": boxes.get(str(e.pk)), "mode": self[f"mode_{e.pk}"], "search": search}

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
        status, pct = data.get("status"), data.get("completion")
        if pct is not None:
            if pct == 100:
                data["status"] = Project.STATUS_COMPLETED
            elif status == Project.STATUS_COMPLETED:
                data["completion"] = 100
        members = data.get("employees")
        if not members:
            self.add_error("employees", "Add at least one member to the project.")
        else:
            for e in members:
                if not data.get(f"mode_{e.pk}"):
                    self.add_error(f"mode_{e.pk}", f"{e.full_name}: choose Office work or Field work.")
        return data

    def save(self, commit=True):
        was_new = self.instance.pk is None
        project = super().save(commit=commit)
        if commit:
            members = list(self.cleaned_data["employees"])
            modes = {e.pk: self.cleaned_data.get(f"mode_{e.pk}") for e in members}
            self.added = services.sync_assignments(project, members, modes, is_new=was_new)
            self.modes = modes
        return project


class LeaveForm(BootstrapMixin, forms.ModelForm):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = LeaveRequest
        fields = ["employee", "leave_type", "start_date", "end_date", "half_day", "reason"]

    def __init__(self, *args, employee=None, pick_employee=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.own_employee = employee
        if pick_employee:
            self.fields["employee"].queryset = Employee.objects.select_related("user").filter(status=Employee.STATUS_ACTIVE)
            self.fields["employee"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        else:
            del self.fields["employee"]
        self.fields["leave_type"].label_from_instance = lambda t: (
            f"{t.name} (unlimited - use after CL is over)" if t.is_lop else t.name)
        self._style()

    def clean(self):
        data = super().clean()
        emp = data.get("employee") if "employee" in self.fields else self.own_employee
        msg = services.validate_leave(
            emp, data.get("leave_type"), data.get("start_date"), data.get("end_date"),
            exclude_pk=self.instance.pk, half_day=bool(data.get("half_day")),
        )
        if msg:
            raise forms.ValidationError(msg)
        return data


class AttendanceForm(BootstrapMixin, forms.ModelForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    in_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    out_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    class Meta:
        model = Attendance
        fields = ["employee", "date", "in_time", "out_time", "work_mode"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.select_related("user")
        self.fields["employee"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        self.fields["work_mode"].label = "Worked at"
        self._style()

    def clean(self):
        data = super().clean()
        if data.get("in_time") and data.get("out_time") and data["out_time"] <= data["in_time"]:
            self.add_error("out_time", "Out time must be after in time.")
        return data


class DesignationForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Designation
        fields = [
            "name", "description", "can_manage_employees", "can_manage_projects",
            "can_manage_leave", "can_manage_attendance",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class LeaveTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "monthly_credit", "annual_credit", "is_lop"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


# ---------------- separate Admin / Employee login pages ----------------
class _PortalLoginForm(AuthenticationForm):
    portal = ""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        manager = services.is_manager(user)
        if self.portal == "admin" and not manager:
            raise forms.ValidationError("This is the Admin / HR login. Please use the Employee login.", code="wrong_portal")
        if self.portal == "employee" and manager:
            raise forms.ValidationError("Admin / HR accounts must sign in from the Admin login.", code="wrong_portal")


class EmployeeLoginForm(_PortalLoginForm):
    portal = "employee"


class AdminLoginForm(_PortalLoginForm):
    portal = "admin"


class DepartmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].error_messages["unique"] = "A department with this name already exists."
        self._style()


class TeamForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "department"]
        error_messages = {
            NON_FIELD_ERRORS: {"unique_together": "This team already exists in the selected department."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].empty_label = "Select department"
        self._style()


class HolidayForm(BootstrapMixin, forms.ModelForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = Holiday
        fields = ["date", "name", "kind"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].error_messages["unique"] = "A holiday is already added for this date."
        self._style()
