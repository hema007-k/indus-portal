from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Attendance, Department, Designation, Employee, LeaveRequest, LeaveType, Project, Team

User = get_user_model()


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "description"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name", "department"]


class DesignationField(serializers.Field):
    """The app sends / receives the designation as plain text; a new name creates the Designation."""

    def to_representation(self, value):
        return value.name if value else ""

    def to_internal_value(self, data):
        name = str(data or "").strip()
        if not name:
            return None
        return Designation.objects.get_or_create(name=name)[0]


class EmployeeSerializer(serializers.ModelSerializer):
    designation = DesignationField(required=False, allow_null=True)
    employee_id = serializers.CharField(required=False, allow_blank=True, max_length=20,
                                        validators=[])
    username = serializers.CharField(write_only=True)
    first_name = serializers.CharField(write_only=True)
    last_name = serializers.CharField(required=False, allow_blank=True, write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True, write_only=True)
    password = serializers.CharField(write_only=True, required=False)
    full_name = serializers.CharField(read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id", "employee_id", "username", "first_name", "last_name", "email", "password",
            "full_name", "department", "department_name", "team", "team_name",
            "designation", "joining_date", "status", "role", "phone",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        u = instance.user
        data.update(username=u.username, first_name=u.first_name, last_name=u.last_name, email=u.email)
        return data

    def validate_username(self, value):
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def _apply_user(self, user, data):
        for field in ("username", "first_name", "last_name", "email"):
            if field in data:
                setattr(user, field, data.pop(field))
        if "password" in data:
            user.set_password(data.pop("password"))
        return user

    def create(self, validated):
        if "password" not in validated:
            raise serializers.ValidationError({"password": "Password is required."})
        user = self._apply_user(User(), validated)
        user.is_active = validated.get("status", Employee.STATUS_ACTIVE) == Employee.STATUS_ACTIVE
        user.save()
        return Employee.objects.create(user=user, **validated)

    def update(self, instance, validated):
        user = self._apply_user(instance.user, validated)
        if "status" in validated:
            user.is_active = validated["status"] == Employee.STATUS_ACTIVE
        user.save()
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        return instance


class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = ["id", "date", "in_time", "out_time", "work_mode"]


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "name", "annual_credit", "monthly_credit", "is_lop"]


class LeaveRequestSerializer(serializers.ModelSerializer):
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = ["id", "employee", "leave_type", "leave_type_name", "start_date", "end_date", "half_day", "days",
                  "reason", "status", "status_display"]
        read_only_fields = ["employee", "days", "status"]


class ProjectSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "description", "status", "status_display", "completion", "start_date", "end_date", "employees"]
        read_only_fields = []
