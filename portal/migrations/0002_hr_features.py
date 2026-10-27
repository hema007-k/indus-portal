import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def designation_text_to_fk(apps, schema_editor):
    """Keep the old free-text designation by turning each distinct value into a Designation row."""
    Employee = apps.get_model("portal", "Employee")
    Designation = apps.get_model("portal", "Designation")
    for emp in Employee.objects.exclude(designation__isnull=True).exclude(designation=""):
        d, _ = Designation.objects.get_or_create(name=emp.designation.strip())
        emp.designation_new = d
        emp.save(update_fields=["designation_new"])


def fk_to_designation_text(apps, schema_editor):
    Employee = apps.get_model("portal", "Employee")
    for emp in Employee.objects.exclude(designation_new__isnull=True):
        emp.designation = emp.designation_new.name
        emp.save(update_fields=["designation"])


def default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("portal", "LeaveType")
    for name, days in (("Casual Leave", 12), ("Sick Leave", 12), ("Earned Leave", 15)):
        LeaveType.objects.get_or_create(name=name, defaults={"annual_credit": days})


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Designation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.CharField(blank=True, help_text="Shown in the employee's personal information", max_length=255)),
                ("can_manage_employees", models.BooleanField(default=False, help_text="Add / edit employees, departments and teams")),
                ("can_manage_projects", models.BooleanField(default=False, help_text="Add / edit projects and assign employees")),
                ("can_manage_leave", models.BooleanField(default=False, help_text="Approve / reject / edit leave")),
                ("can_manage_attendance", models.BooleanField(default=False, help_text="Add / edit attendance records")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="LeaveType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True)),
                ("annual_credit", models.PositiveSmallIntegerField(default=12, help_text="Leave days credited to every employee per year")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="LeaveRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("days", models.PositiveSmallIntegerField(default=0, help_text="Working days (Mon-Fri) - calculated automatically")),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leaves", to="portal.employee")),
                ("leave_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requests", to="portal.leavetype")),
            ],
            options={"ordering": ["-start_date", "-id"]},
        ),
        # designation: free text -> Designation table (data is converted, not lost)
        migrations.AddField(
            model_name="employee",
            name="designation_new",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="employees", to="portal.designation"),
        ),
        migrations.RunPython(designation_text_to_fk, fk_to_designation_text),
        migrations.RemoveField(model_name="employee", name="designation"),
        migrations.RenameField(model_name="employee", old_name="designation_new", new_name="designation"),
        migrations.AlterField(
            model_name="employee",
            name="employee_id",
            field=models.CharField(blank=True, help_text="Unique code. Leave blank to auto-generate (EMP001, EMP002 ...)", max_length=20, unique=True, verbose_name="Employee Code"),
        ),
        migrations.AddField(
            model_name="attendance",
            name="work_mode",
            field=models.CharField(choices=[("office", "Office"), ("field", "Field")], default="office", max_length=6),
        ),
        migrations.AddField(
            model_name="project",
            name="completion",
            field=models.PositiveSmallIntegerField(default=0, help_text="0 - 100. Setting 100 marks the project as completed.", validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name="Completion %"),
        ),
        migrations.RunPython(default_leave_types, migrations.RunPython.noop),
    ]
