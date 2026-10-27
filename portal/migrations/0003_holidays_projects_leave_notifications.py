import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_data(apps, schema_editor):
    LeaveType = apps.get_model("portal", "LeaveType")
    Project = apps.get_model("portal", "Project")
    ProjectAssignment = apps.get_model("portal", "ProjectAssignment")

    # Casual Leave: 1.5 days every month. Loss of Pay: unlimited, used after the CL credit is over.
    cl, _ = LeaveType.objects.get_or_create(name="Casual Leave", defaults={"annual_credit": 18})
    cl.monthly_credit = decimal.Decimal("1.5")
    cl.annual_credit = 18
    cl.save()
    LeaveType.objects.get_or_create(name="Loss of Pay", defaults={"annual_credit": 0, "is_lop": True})
    LeaveType.objects.filter(name="Loss of Pay").update(is_lop=True)

    # every existing project member becomes an office assignment
    for project in Project.objects.all():
        for emp in project.employees.all():
            ProjectAssignment.objects.get_or_create(
                project=project, employee=emp, defaults={"work_mode": "office", "assigned_on": project.start_date}
            )


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0002_hr_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="leavetype",
            name="monthly_credit",
            field=models.DecimalField(
                decimal_places=1, default=decimal.Decimal("0"), max_digits=4,
                help_text="Days credited every month (e.g. 1.5 for Casual Leave). 0 = use the yearly credit instead",
            ),
        ),
        migrations.AddField(
            model_name="leavetype",
            name="is_lop",
            field=models.BooleanField(
                default=False, verbose_name="Loss of Pay (unlimited)",
                help_text="Loss of Pay has no credit limit - used when the Casual Leave credit is finished",
            ),
        ),
        migrations.AddField(
            model_name="leaverequest",
            name="half_day",
            field=models.BooleanField(default=False, help_text="Half day (single date only)"),
        ),
        migrations.AlterField(
            model_name="leaverequest",
            name="days",
            field=models.DecimalField(
                decimal_places=1, default=decimal.Decimal("0"), max_digits=4,
                help_text="Working days (holidays excluded) - calculated automatically",
            ),
        ),
        migrations.CreateModel(
            name="Holiday",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(unique=True)),
                ("name", models.CharField(max_length=120)),
                ("kind", models.CharField(
                    choices=[("government", "Government holiday"), ("company", "Company holiday")],
                    default="government", max_length=10)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["date"]},
        ),
        migrations.CreateModel(
            name="ProjectAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("work_mode", models.CharField(
                    choices=[("office", "Office"), ("field", "Field")], default="office", max_length=6)),
                ("assigned_on", models.DateField(blank=True, null=True)),
                ("employee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="portal.employee")),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="portal.project")),
            ],
            options={"unique_together": {("project", "employee")}},
        ),
        migrations.CreateModel(
            name="ProjectUpdate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("percent", models.PositiveSmallIntegerField(validators=[
                    django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("note", models.CharField(blank=True, max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("employee", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="project_updates", to="portal.employee")),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="updates", to="portal.project")),
            ],
            options={"ordering": ["-date", "-id"], "unique_together": {("project", "employee", "date")}},
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(default="info", max_length=20)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_read", models.BooleanField(default=False)),
                ("whatsapp", models.CharField(default="link", max_length=10)),
                ("recipient", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="portal.employee")),
                ("sender", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.RunPython(seed_data, migrations.RunPython.noop),
    ]
