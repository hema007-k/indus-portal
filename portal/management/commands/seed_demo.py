
import random
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.models import (
    Attendance, Department, Designation, Employee, Holiday, LeaveRequest, LeaveType, Project, ProjectAssignment,
    ProjectUpdate, Team,
)
from portal import services

User = get_user_model()


class Command(BaseCommand):
    help = "Create demo data (admin / employee accounts, departments, projects, attendance)."

    def handle(self, *args, **opts):
        if Employee.objects.exists():
            self.stdout.write("Demo data already present - skipping.")
            return

        # Leave types (the migration also creates these; this keeps seed_demo safe on its own)
        # Casual Leave: 1.5 days credited every month.  Loss of Pay: unlimited, used after CL is over.
        cl, _ = LeaveType.objects.get_or_create(name="Casual Leave", defaults={"annual_credit": 18})
        LeaveType.objects.filter(pk=cl.pk).update(monthly_credit=1.5, annual_credit=18)
        lop, _ = LeaveType.objects.get_or_create(name="Loss of Pay", defaults={"annual_credit": 0})
        LeaveType.objects.filter(pk=lop.pk).update(is_lop=True)

        # Designations. The can_manage_* flags are the designation-based permissions.
        def desig(name, description, **flags):
            d, _ = Designation.objects.get_or_create(name=name, defaults={"description": description, **flags})
            return d

        d_super = desig("Super Admin", "Full access to the whole portal", can_manage_employees=True,
                        can_manage_projects=True, can_manage_leave=True, can_manage_attendance=True)
        d_hr = desig("HR Manager", "Manages employees, leave and attendance", can_manage_employees=True,
                     can_manage_projects=True, can_manage_leave=True, can_manage_attendance=True)
        d_pm = desig("Project Manager", "Creates projects and assigns the team", can_manage_projects=True)
        d_sup = desig("Survey Supervisor", "Leads field survey work and can manage projects", can_manage_projects=True)
        d_mod = desig("Modeling Specialist", "Hydrodynamic and wave modeling")
        d_tech = desig("Biological Oceanography Technician", "Marine sampling and lab work")

        # Departments
        survey = Department.objects.create(
            name="Survey",
            description="Survey department."
        )

        modeling = Department.objects.create(
            name="Modeling",
            description="Modeling department."
        )

        bio_oceanography = Department.objects.create(
            name="Biological Oceanography",
            description="Biological Oceanography department."
        )

        # Teams
        t_survey = Team.objects.create(
            name="Survey Team",
            department=survey
        )

        t_modeling = Team.objects.create(
            name="Modeling Team",
            department=modeling
        )

        t_bio = Team.objects.create(
            name="Biological Oceanography Team",
            department=bio_oceanography
        )

        # Create users and employees
        def make(
            username,
            first,
            last,
            emp_id,
            dept,
            team,
            desig,
            role,
            password,
            superuser=False
        ):
            if superuser:
                user = User.objects.create_superuser(
                    username,
                    f"{username}@example.com",
                    password
                )
            else:
                user = User.objects.create_user(
                    username,
                    f"{username}@example.com",
                    password
                )

            user.first_name = first
            user.last_name = last
            user.save()

            return Employee.objects.create(
                user=user,
                employee_id=emp_id,
                department=dept,
                team=team,
                designation=desig,
                joining_date=date.today() - timedelta(
                    days=random.randint(60, 900)
                ),
                role=role,
            )

        # Admin and HR
        make(
            "admin",
            "System",
            "Admin",
            "EMP001",
            modeling,
            t_modeling,
            d_super,
            Employee.ROLE_ADMIN,
            "admin123",
            True
        )

        make(
            "hr",
            "Hema",
            "Raj",
            "EMP002",
            survey,
            t_survey,
            d_hr,
            Employee.ROLE_HR,
            "hr12345"
        )

        # Employees
        e1 = make(
            "arun",
            "Arun",
            "Kumar",
            "EMP003",
            survey,
            t_survey,
            d_sup,
            Employee.ROLE_EMPLOYEE,
            "arun123"
        )

        e2 = make(
            "priya",
            "Priya",
            "S",
            "EMP004",
            modeling,
            t_modeling,
            d_mod,
            Employee.ROLE_EMPLOYEE,
            "priya123"
        )

        e3 = make(
            "vijay",
            "Vijay",
            "M",
            "EMP005",
            bio_oceanography,
            t_bio,
            d_tech,
            Employee.ROLE_EMPLOYEE,
            "vijay123"
        )

        # Projects
        p1 = Project.objects.create(
            name="Survey Project",
            description="Survey data collection and analysis.",
            status=Project.STATUS_INPROGRESS,
            start_date=date.today() - timedelta(days=30)
        )
        p1.completion = 60
        p1.save()
        p1.employees.set([e1, e2, e3])  # more than two employees on one project

        p2 = Project.objects.create(
            name="Modeling Project",
            description="Scientific modeling and data analysis.",
            status=Project.STATUS_INPROGRESS,
            start_date=date.today() - timedelta(days=15),
            completion=35,
        )
        p2.employees.set([e2, e1])

        p3 = Project.objects.create(
            name="Biological Oceanography Study",
            description="Study of marine organisms and ocean ecosystems.",
            status=Project.STATUS_COMPLETED,
            completion=100,
            start_date=date.today() - timedelta(days=120),
            end_date=date.today() - timedelta(days=40),
        )
        p3.employees.set([e1, e3])

        # Who works in the office / in the field on each project
        for proj, rows in (
            (p1, ((e1, "field"), (e2, "office"), (e3, "office"))),
            (p2, ((e2, "office"), (e1, "office"))),
            (p3, ((e1, "field"), (e3, "office"))),
        ):
            for emp, mode in rows:
                ProjectAssignment.objects.update_or_create(
                    project=proj, employee=emp, defaults={"work_mode": mode, "assigned_on": proj.start_date})

        # Sample government holidays (EDIT / VERIFY these on the Holidays page for your state & year)
        for hd, hname in (
            (date(2026, 1, 1), "New Year"), (date(2026, 1, 15), "Pongal"), (date(2026, 1, 26), "Republic Day"),
            (date(2026, 5, 1), "May Day"), (date(2026, 8, 15), "Independence Day"),
            (date(2026, 10, 2), "Gandhi Jayanti"), (date(2026, 12, 25), "Christmas"),
        ):
            Holiday.objects.get_or_create(date=hd, defaults={"name": hname, "kind": Holiday.KIND_GOVT})

        # Attendance for the previous 30 days
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        leave_start = monday - timedelta(days=14)          # a Monday two weeks ago
        leave_end = leave_start + timedelta(days=1)        # ... and the Tuesday after it
        leave_days = {leave_start, leave_end}

        for emp in (e1, e2, e3):
            d = today - timedelta(days=30)

            while d < today:
                if services.is_working_day(d) and random.random() > 0.15 and not (emp == e1 and d in leave_days):
                    Attendance.objects.create(
                        employee=emp,
                        date=d,
                        work_mode=random.choice(["office", "office", "field"]),
                        in_time=time(
                            9,
                            random.randint(0, 30)
                        ),
                        out_time=time(
                            18,
                            random.randint(0, 30)
                        )
                    )

                d += timedelta(days=1)

        # A couple of leave records so leave credit / working-day maths can be seen straight away
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(
            employee=e1, leave_type=casual, start_date=leave_start,
            end_date=leave_end, reason="Family function",
            status=LeaveRequest.STATUS_APPROVED,
        )
        LeaveRequest.objects.create(
            employee=e2, leave_type=casual, start_date=monday + timedelta(days=7),
            end_date=monday + timedelta(days=8), reason="Personal", status=LeaveRequest.STATUS_PENDING,
        )

        for emp, phone in ((e1, "9876500001"), (e2, "9876500002"), (e3, "9876500003")):
            Employee.objects.filter(pk=emp.pk).update(phone=phone)
        for emp, pct in ((e1, 70), (e2, 55), (e3, 40)):
            ProjectUpdate.objects.update_or_create(
                project=p1, employee=emp, date=today, defaults={"percent": pct, "note": "Demo update"})
        services.recompute_completion(p1)

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data created successfully.\n"
                "  Admin : admin / admin123\n"
                "  HR    : hr / hr12345\n"
                "  User  : arun / arun123\n"
                "  User  : priya / priya123\n"
                "  User  : vijay / vijay123"
            )
        )
