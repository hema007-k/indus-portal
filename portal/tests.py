from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Designation, Employee, Project

User = get_user_model()


class PortalSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    def test_login_page(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_redirect_when_anonymous(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_employee_pages_and_clock(self):
        self.login("arun", "arun123")
        for name in ("dashboard", "project_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.post(reverse("clock_in"), follow=True).status_code, 200)
        self.assertEqual(self.client.post(reverse("clock_out"), follow=True).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 403)

    def test_manager_pages(self):
        self.login("admin", "admin123")
        for name in ("dashboard", "employee_list", "employee_create", "project_list", "project_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        emp = Employee.objects.get(user__username="arun")
        self.assertEqual(self.client.get(reverse("employee_edit", args=[emp.pk])).status_code, 200)
        p = Project.objects.first()
        self.assertEqual(self.client.get(reverse("project_edit", args=[p.pk])).status_code, 200)

    def test_employee_detail(self):
        self.login("admin", "admin123")
        emp = Employee.objects.get(user__username="arun")
        for q in ("", "?from=home"):
            r = self.client.get(reverse("employee_detail", args=[emp.pk]) + q)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Arun")
        self.client.logout()
        self.login("priya", "priya123")  # an employee cannot open somebody else's details
        self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk])).status_code, 403)
        self.client.logout()
        self.login("arun", "arun123")  # ... but can open their own
        self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk])).status_code, 200)

    def test_add_employee(self):
        self.login("hr", "hr12345")
        resp = self.client.post(reverse("employee_create"), {
            "employee_id": "EMP900", "username": "newbie", "first_name": "New", "last_name": "Bie",
            "email": "n@example.com", "password": "pass12345",
            "designation": Designation.objects.create(name="Tester").pk,
            "status": "active", "role": "employee",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_api_token_flow(self):
        r = self.client.post("/api/auth/login/", {"username": "arun", "password": "arun123"})
        self.assertEqual(r.status_code, 200)
        token = r.json()["token"]
        r = self.client.get("/api/dashboard/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("month_summary", r.json())
        r = self.client.get("/api/employees/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.status_code, 403)

    def _token(self, username, password):
        r = self.client.post("/api/auth/login/", {"username": username, "password": password})
        return {"HTTP_AUTHORIZATION": f"Token {r.json()['token']}"}

    def test_api_manager_attendance_endpoints(self):
        emp = Employee.objects.get(user__username="arun")
        mgr = self._token("hr", "hr12345")
        rows = self.client.get("/api/attendance/today/", **mgr).json()
        self.assertTrue(any(r["employee_id"] == emp.employee_id for r in rows))
        detail = self.client.get(f"/api/employees/{emp.pk}/attendance/", **mgr).json()
        self.assertIn("summary", detail)
        self.assertEqual(len(detail["history"]), 30)
        staff = self._token("arun", "arun123")
        self.assertEqual(self.client.get("/api/attendance/today/", **staff).status_code, 403)
        self.assertEqual(self.client.get(f"/api/employees/{emp.pk}/attendance/", **staff).status_code, 403)

    def test_api_employee_crud_for_app(self):
        mgr = self._token("admin", "admin123")
        r = self.client.post("/api/employees/", {
            "employee_id": "EMP901", "username": "appuser", "first_name": "App", "password": "pass12345",
            "role": "employee", "status": "active",
        }, content_type="application/json", **mgr)
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["id"]
        r = self.client.patch(f"/api/employees/{pk}/", {"designation": "QA"}, content_type="application/json", **mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["designation"], "QA")
        self.assertEqual(self.client.delete(f"/api/employees/{pk}/", **mgr).status_code, 204)


class OrganizationTests(TestCase):
    """Department / Team create, edit, delete (HR + Admin only)."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_org_page_and_permissions(self):
        self.client.login(username="admin", password="admin123")
        for name in ("organization", "department_create", "team_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.client.logout()
        self.client.login(username="arun", password="arun123")
        for name in ("organization", "department_create", "team_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_create_department_and_team(self):
        from .models import Department, Team
        self.client.login(username="hr", password="hr12345")
        r = self.client.post(reverse("department_create"), {"name": "Legal", "description": "Contracts"})
        self.assertRedirects(r, reverse("organization"))
        dept = Department.objects.get(name="Legal")
        r = self.client.post(reverse("team_create"), {"name": "Compliance", "department": dept.pk})
        self.assertRedirects(r, reverse("organization"))
        self.assertTrue(Team.objects.filter(name="Compliance", department=dept).exists())
        # duplicates are rejected with a friendly message, not a 500
        r = self.client.post(reverse("department_create"), {"name": "Legal"})
        self.assertContains(r, "already exists")
        r = self.client.post(reverse("team_create"), {"name": "Compliance", "department": dept.pk})
        self.assertContains(r, "already exists in the selected department")

    def test_edit_and_delete(self):
        from .models import Department, Team
        self.client.login(username="admin", password="admin123")
        dept = Department.objects.create(name="Temp")
        team = Team.objects.create(name="T1", department=dept)
        self.client.post(reverse("team_edit", args=[team.pk]), {"name": "T1-renamed", "department": dept.pk})
        team.refresh_from_db()
        self.assertEqual(team.name, "T1-renamed")
        self.assertEqual(self.client.get(reverse("department_delete", args=[dept.pk])).status_code, 200)
        self.client.post(reverse("department_delete", args=[dept.pk]))
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    def test_employee_team_must_match_department(self):
        from .models import Department, Team
        self.client.login(username="admin", password="admin123")
        d1, d2 = Department.objects.create(name="D-one"), Department.objects.create(name="D-two")
        t2 = Team.objects.create(name="Only-in-two", department=d2)
        r = self.client.post(reverse("employee_create"), {
            "employee_id": "EMP901", "username": "mismatch", "first_name": "Mis", "password": "pass12345",
            "department": d1.pk, "team": t2.pk, "status": "active", "role": "employee",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "belongs to")


from datetime import date, time, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from . import services  # noqa: E402
from .models import (  # noqa: E402
    Attendance, Department, Holiday, LeaveRequest, LeaveType, Notification, ProjectAssignment, ProjectUpdate, Team,
)


class FeatureTests(TestCase):
    """Employee code, leave credit, working days, project metrics, role / designation permissions."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    # ---- employee code
    def test_employee_code_is_unique_and_auto_generated(self):
        self.login("hr", "hr12345")
        for i in range(2):
            r = self.client.post(reverse("employee_create"), {
                "employee_id": "", "username": f"auto{i}", "first_name": "Auto", "password": "pass12345",
                "status": "active", "role": "employee",
            })
            self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        codes = list(Employee.objects.values_list("employee_id", flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertIn("EMP006", codes)
        self.assertIn("EMP007", codes)
        # a manually typed duplicate is refused
        r = self.client.post(reverse("employee_create"), {
            "employee_id": "emp003", "username": "dupe", "first_name": "D", "password": "pass12345",
            "status": "active", "role": "employee",
        })
        self.assertContains(r, "already used")

    # ---- separate logins
    def test_separate_admin_and_employee_login(self):
        r = self.client.post(reverse("login"), {"username": "admin", "password": "admin123"})
        self.assertContains(r, "Admin / HR accounts must sign in")
        r = self.client.post(reverse("admin_login"), {"username": "arun", "password": "arun123"})
        self.assertContains(r, "This is the Admin / HR login")
        self.assertEqual(self.client.post(reverse("admin_login"), {"username": "admin", "password": "admin123"}).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("login"), {"username": "arun", "password": "arun123"}).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 302)
        self.assertIn("admin-login", self.client.get(reverse("employee_list"))["Location"])

    # ---- designation-based permissions
    def test_designation_permissions(self):
        self.login("arun", "arun123")  # Survey Supervisor: can manage projects only
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("attendance_list")).status_code, 403)
        self.client.logout()
        self.login("priya", "priya123")  # Modeling Specialist: nothing to manage
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("leave_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("my_profile")).status_code, 200)
        # giving the designation a flag opens the page
        Designation.objects.filter(name="Modeling Specialist").update(can_manage_attendance=True)
        self.assertEqual(self.client.get(reverse("attendance_list")).status_code, 200)

    def test_only_manager_role_can_make_admins(self):
        Designation.objects.filter(name="Modeling Specialist").update(can_manage_employees=True)
        self.login("priya", "priya123")
        admin_emp = self.emp("admin")
        self.assertEqual(self.client.get(reverse("employee_edit", args=[admin_emp.pk])).status_code, 403)
        r = self.client.get(reverse("employee_create"))
        self.assertNotContains(r, 'value="admin"')

    # ---- leave credit + validation
    def test_leave_credit_and_validation(self):
        arun = self.emp("arun")
        casual = LeaveType.objects.get(name="Casual Leave")
        seeded = LeaveRequest.objects.get(employee=arun, status="approved")
        bal = services.leave_balances(arun, seeded.start_date.year)
        row = next(r for r in bal["rows"] if r["type"] == casual)
        credit = Decimal("1.5") * services.months_credited(arun, seeded.start_date.year)  # 1.5 days every month
        self.assertEqual((seeded.days, row["credit"], row["used"], row["balance"]), (2, credit, 2, credit - 2))
        self.login("arun", "arun123")
        lop = LeaveType.objects.get(name="Loss of Pay")
        start = date.today() + timedelta(days=30)
        while start.weekday() != 0:
            start += timedelta(days=1)
        end = start + timedelta(days=4)  # Mon-Fri
        r = self.client.post(reverse("leave_create"), {
            "leave_type": lop.pk, "start_date": start, "end_date": end, "reason": "trip",
        })
        self.assertEqual(r.status_code, 302)
        leave = LeaveRequest.objects.get(employee=arun, reason="trip")
        self.assertEqual((leave.days, leave.status), (services.leave_days_for(start, end), "pending"))
        # HR / managers got a notification about the new request
        self.assertTrue(Notification.objects.filter(recipient=self.emp("hr"), kind="leave").exists())
        # overlapping request refused
        r = self.client.post(reverse("leave_create"), {
            "leave_type": lop.pk, "start_date": start, "end_date": start, "reason": "again"})
        self.assertContains(r, "already has leave")
        # more than the Casual Leave credit refused -> must be applied as LOP
        far = start + timedelta(days=60)
        r = self.client.post(reverse("leave_create"), {
            "leave_type": casual.pk, "start_date": far, "end_date": far + timedelta(days=25)})
        if far.year == (far + timedelta(days=25)).year:
            self.assertContains(r, "Loss of Pay")
        # an employee cannot approve; HR can
        self.assertEqual(self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "approve"}).status_code, 403)
        self.client.logout()
        self.login("hr", "hr12345")
        self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "approve"})
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

    # ---- working-day maths
    def test_period_summary_office_field_leave(self):
        emp = self.emp("vijay")
        Attendance.objects.filter(employee=emp).delete()
        LeaveRequest.objects.filter(employee=emp).delete()
        mon = date(2026, 3, 2)  # a Monday
        for i, mode in enumerate(["office", "office", "field"]):  # Mon, Tue, Wed present
            Attendance.objects.create(employee=emp, date=mon + timedelta(days=i), in_time=time(9), out_time=time(18), work_mode=mode)
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=emp, leave_type=casual, start_date=mon + timedelta(days=3),
                                    end_date=mon + timedelta(days=3), status="approved")  # Thu on leave
        s = services.period_summary(emp, mon, mon + timedelta(days=6), today=mon + timedelta(days=7))
        # Mon-Sun: 6 working days; 3 present (2 office, 1 field), 1 leave, Fri + Sat absent
        # (Mon-Sat are working days - Sunday is off; 7-Mar is the 1st Saturday)
        self.assertEqual((s["working_days"], s["present"], s["office"], s["field"]), (6, 3, 2, 1))
        self.assertEqual((s["leave"], s["absent"], s["net_working_days"], s["percent"]), (1, 2, 5, 60))

    def test_project_working_days_consider_leave(self):
        from .models import Project

        a, b, c = self.emp("arun"), self.emp("priya"), self.emp("vijay")
        LeaveRequest.objects.filter(employee__in=[a, b, c]).delete()
        proj = Project.objects.create(name="Maths", start_date=date(2026, 3, 2), end_date=date(2026, 3, 13))
        proj.employees.set([a, b, c])  # three employees on one project
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=a, leave_type=casual, start_date=date(2026, 3, 4),
                                    end_date=date(2026, 3, 5), status="approved")
        m = services.project_metrics(proj, today=date(2026, 4, 1))
        self.assertEqual(m["span_days"], 11)  # Mon-Sat of week 1 (7-Mar is a working Saturday) + Mon-Fri of week 2
        self.assertEqual(m["leave_days"], 2)
        self.assertEqual(m["man_days"], 11 * 3 - 2)
        self.assertEqual(sorted(r["net_days"] for r in m["rows"]), [9, 11, 11])
        # leave that is only pending or rejected does not reduce working days
        LeaveRequest.objects.create(employee=b, leave_type=casual, start_date=date(2026, 3, 9),
                                    end_date=date(2026, 3, 9), status="pending")
        self.assertEqual(services.project_metrics(proj, today=date(2026, 4, 1))["leave_days"], 2)

    # ---- project form: many employees, completion
    def test_project_many_employees_and_completion(self):
        self.login("admin", "admin123")
        ids = list(Employee.objects.values_list("pk", flat=True))[:4]
        r = self.client.post(reverse("project_create"), {
            "name": "Big team", "description": "", "status": "inprogress", "completion": 100,
            "employees": ids, **{f"mode_{i}": "field" for i in ids},
        })
        self.assertEqual(r.status_code, 302)
        from .models import Project
        p = Project.objects.get(name="Big team")
        self.assertEqual(p.employees.count(), 4)
        self.assertEqual((p.completion, p.status), (100, "completed"))
        self.assertContains(self.client.get(reverse("project_detail", args=[p.pk])), "Big team")

    # ---- every page renders, with monthly + yearly filters
    def test_pages_render_with_period_filters(self):
        for who, pw, names in (
            ("admin", "admin123", ["dashboard", "employee_list", "organization", "project_list", "leave_list",
                                   "attendance_list", "attendance_create", "leave_create", "designation_create",
                                   "leavetype_create"]),
            ("arun", "arun123", ["dashboard", "my_profile", "project_list", "leave_list", "leave_create"]),
        ):
            self.client.logout()
            self.login(who, pw)
            for name in names:
                for q in ("", "?period=month&month=2026-03", "?period=year&year=2026", "?period=all"):
                    r = self.client.get(reverse(name) + q)
                    self.assertEqual(r.status_code, 200, f"{who} {name} {q}")
        emp = self.emp("arun")
        self.client.logout()
        self.login("admin", "admin123")
        for q in ("?period=year&year=2026", "?period=month&month=2026-02"):
            self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk]) + q).status_code, 200)

    def test_employee_search(self):
        self.login("hr", "hr12345")
        r = self.client.get(reverse("employee_list") + "?q=priya")
        self.assertContains(r, "Priya")
        self.assertNotContains(r, "Vijay")
        r = self.client.get(reverse("employee_list") + "?q=EMP005")
        self.assertContains(r, "Vijay")

    def test_attendance_edit_by_permission(self):
        self.login("hr", "hr12345")
        emp = self.emp("arun")
        r = self.client.post(reverse("attendance_create"), {
            "employee": emp.pk, "date": "2026-01-05", "in_time": "09:00", "out_time": "17:30", "work_mode": "field"})
        self.assertEqual(r.status_code, 302)
        rec = Attendance.objects.get(employee=emp, date=date(2026, 1, 5))
        self.assertEqual((rec.work_mode, rec.out_time), ("field", time(17, 30)))

    def test_check_db_command(self):
        from io import StringIO
        out = StringIO()
        call_command("check_db", stdout=out)
        self.assertIn("Database OK", out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    def test_api_leave_and_clock_mode(self):
        r = self.client.post("/api/auth/login/", {"username": "arun", "password": "arun123"})
        h = {"HTTP_AUTHORIZATION": f"Token {r.json()['token']}"}
        r = self.client.post("/api/attendance/clock-in/", {"work_mode": "field"}, content_type="application/json", **h)
        self.assertEqual(r.json()["attendance"]["work_mode"], "field")
        self.assertEqual(self.client.get("/api/leave-balance/", **h).json()["totals"]["credit"],
                         services.plain(services.leave_balances(self.emp("arun"), date.today().year)["totals"]["credit"]))
        d = self.client.get("/api/dashboard/", **h).json()
        self.assertEqual(d["designation"], "Survey Supervisor")


class V6FeatureTests(TestCase):
    """Holidays, CL / LOP, project members + daily progress, notifications, date format."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    # ---- holidays
    def test_second_saturday_sunday_and_government_holiday_are_off(self):
        self.assertEqual(services.off_reason(date(2026, 3, 14), {}), "2nd Saturday")
        self.assertIsNone(services.off_reason(date(2026, 3, 7), {}))    # 1st Saturday works
        self.assertEqual(services.off_reason(date(2026, 3, 15), {}), "Sunday")
        Holiday.objects.create(date=date(2026, 3, 18), name="Test Day")
        self.assertEqual(services.working_days_between(date(2026, 3, 16), date(2026, 3, 20)), 4)

    def test_only_admin_can_declare_company_holiday(self):
        self.login("arun", "arun123")
        self.assertEqual(self.client.post(reverse("holiday_today"), {"name": "x"}).status_code, 403)
        self.client.logout()
        self.login("admin", "admin123")
        self.client.post(reverse("holiday_today"), {"name": "Cyclone"})
        h = Holiday.objects.get(date=date.today())
        self.assertEqual((h.kind, h.name), ("company", "Cyclone"))
        self.assertEqual(services.today_holiday(), "Cyclone")
        self.client.post(reverse("holiday_today"), {"action": "cancel"})
        self.assertFalse(Holiday.objects.filter(date=date.today(), kind="company").exists())

    # ---- leave: CL 1.5 / month, then LOP
    def test_casual_leave_then_lop(self):
        arun = self.emp("arun")
        casual = LeaveType.objects.get(name="Casual Leave")
        lop = LeaveType.objects.get(name="Loss of Pay")
        LeaveRequest.objects.filter(employee=arun).delete()
        today = date.today()
        months = services.months_credited(arun, today.year)
        bal = services.leave_balances(arun, today.year)
        cl = next(r for r in bal["rows"] if r["type"] == casual)
        self.assertEqual(cl["credit"], Decimal("1.5") * months)
        self.assertTrue(next(r for r in bal["rows"] if r["type"] == lop)["unlimited"])
        # more CL than the credit -> error that points to LOP; LOP itself is never limited
        d = date(today.year, today.month, 1)
        while d.weekday() != 0:
            d += timedelta(days=1)
        end = d + timedelta(days=int(cl["credit"]) * 2 + 10)
        if end.year == d.year:
            msg = services.validate_leave(arun, casual, d, end)
            self.assertIn("Loss of Pay", msg or "")
            self.assertIsNone(services.validate_leave(arun, lop, d, end))
        # half day = 0.5
        half = services.leave_days_for(d, d, True)
        self.assertEqual(half, Decimal("0.5"))

    def test_leave_overview_lists_people_without_leave(self):
        LeaveRequest.objects.all().delete()
        ov = services.leave_overview()
        self.assertEqual(len(ov["no_leave"]), len(ov["rows"]))
        self.login("hr", "hr12345")
        self.assertContains(self.client.get(reverse("leave_list")), "No leave taken")

    # ---- projects: members + office/field, daily progress, automatic %
    def test_project_needs_member_and_work_type(self):
        self.login("admin", "admin123")
        a, b = self.emp("arun"), self.emp("priya")
        r = self.client.post(reverse("project_create"), {"name": "NoMember", "status": "inprogress", "completion": 0})
        self.assertContains(r, "at least one member")
        r = self.client.post(reverse("project_create"), {
            "name": "NoMode", "status": "inprogress", "completion": 0, "employees": [a.pk]})
        self.assertContains(r, "choose Office work or Field work")
        r = self.client.post(reverse("project_create"), {
            "name": "Two", "status": "inprogress", "completion": 0, "start_date": "2026-03-02", "end_date": "2026-03-13",
            "employees": [a.pk, b.pk], f"mode_{a.pk}": "field", f"mode_{b.pk}": "office"})
        self.assertRedirects(r, reverse("notifications"))     # link mode -> WhatsApp buttons page
        p = Project.objects.get(name="Two")
        self.assertEqual(ProjectAssignment.objects.get(project=p, employee=a).work_mode, "field")
        self.assertEqual(Notification.objects.filter(kind="project", recipient__in=[a, b]).count(), 2)

    def test_daily_update_drives_project_percentage_and_completed_list(self):
        p = Project.objects.create(name="Prog", start_date=date.today() - timedelta(days=3))
        a, b = self.emp("arun"), self.emp("priya")
        p.employees.set([a, b])
        services.sync_assignments(p, [a, b], {a.pk: "office", b.pk: "field"})
        self.login("arun", "arun123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 60, "note": "survey done"})
        p.refresh_from_db()
        self.assertEqual(p.completion, 30)                     # (60 + 0) / 2 members
        self.client.logout()
        self.login("priya", "priya123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 100})
        self.client.logout()
        self.login("arun", "arun123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 100, "note": "survey done"})
        p.refresh_from_db()
        self.assertEqual((p.completion, p.status), (100, "completed"))
        self.assertEqual(ProjectUpdate.objects.filter(project=p).count(), 2)  # one row per person per day
        # completed project is listed under completed on the employee's project page, admin sees the updates
        self.assertContains(self.client.get(reverse("project_list")), "completed projects")
        self.client.logout()
        self.login("admin", "admin123")
        self.assertContains(self.client.get(reverse("project_detail", args=[p.pk])), "survey done")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_leave_inside_assignment_is_not_counted(self):
        a = self.emp("arun")
        LeaveRequest.objects.filter(employee=a).delete()
        p = Project.objects.create(name="Ten", start_date=date(2026, 3, 2), end_date=date(2026, 3, 13))
        p.employees.set([a])
        services.sync_assignments(p, [a], {a.pk: "office"}, is_new=True)
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=a, leave_type=casual, start_date=date(2026, 3, 6),
                                    end_date=date(2026, 3, 6), status="approved")
        row = services.project_metrics(p, today=date(2026, 4, 1))["rows"][0]
        self.assertEqual((row["span_days"], row["leave_days"], row["net_days"]), (11, 1, 10))

    # ---- notifications / WhatsApp link
    def test_whatsapp_link_and_phone(self):
        from . import notifications
        self.assertEqual(notifications.normalize_phone("98765 43210"), "919876543210")
        self.assertTrue(notifications.wa_link("9876543210", "hi there").startswith("https://wa.me/919876543210?text=hi"))
        self.assertEqual(notifications.normalize_phone(""), "")

    # ---- display rules
    def test_date_format_title_and_code(self):
        self.login("arun", "arun123")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "EMP003")
        self.assertContains(r, "Survey Supervisor")
        self.assertNotContains(r, ">Employee<")
        self.assertRegex(r.content.decode(), r"\d{2}-[A-Z][a-z]{2}-\d{4}")
        self.client.logout()
        self.login("hr", "hr12345")
        r = self.client.get(reverse("employee_list"))
        self.assertContains(r, "Attendance")
        for name in ("holiday_list", "notifications", "holiday_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


# ---------------------------------------------------------------- v7: speed, no-reload (Turbo), member search
class V7SpeedAndTurboTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        desig = Designation.objects.first()
        for i in range(25):
            u = User.objects.create_user(f"bulk{i}", password="x", first_name=f"Bulk{i}")
            Employee.objects.create(user=u, designation=desig)

    def queries(self, name, *args):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse(name, args=args))
        self.assertEqual(resp.status_code, 200, name)
        return len(ctx)

    def test_manager_pages_use_a_fixed_number_of_queries(self):
        """With 28+ employees the pages still need only a handful of database round trips.
        (Before v7 the Admin home needed ~150 - one set per employee - which is what made a hosted
        PostgreSQL feel slow.)"""
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        self.assertLess(self.queries("dashboard"), 25)
        self.assertLess(self.queries("attendance_list"), 15)
        self.assertLess(self.queries("leave_list"), 15)
        self.assertLess(self.queries("employee_list"), 12)
        self.assertLess(self.queries("project_list"), 20)

    def test_bulk_summaries_match_single_employee_summaries(self):
        from datetime import date as d

        from . import services

        emps = list(Employee.objects.select_related("user"))
        start, end, today = d(2026, 10, 1), d(2026, 10, 31), d(2026, 10, 27)
        bulk = services.bulk_period_summaries(emps, start, end, today)
        for e in emps:
            self.assertEqual(bulk[e.pk], services.period_summary(e, start, end, today), e.employee_id)

    def test_leave_overview_matches_per_employee_balances(self):
        from . import services

        ov = services.leave_overview(2026)
        for row in ov["rows"]:
            single = services.leave_balances(row["employee"], 2026)["totals"]
            self.assertEqual(row["credit"], single["credit"])
            self.assertEqual(row["balance"], single["balance"])

    def test_turbo_form_errors_come_back_as_422(self):
        """Turbo only re-draws a submitted form when the status is 4xx; plain browsers still get 200."""
        self.assertTrue(self.client.login(username="hr", password="hr12345"))
        url = reverse("employee_create")
        turbo = {"HTTP_ACCEPT": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml"}
        self.assertEqual(self.client.post(url, {}, **turbo).status_code, 422)
        self.assertEqual(self.client.post(url, {}).status_code, 200)

    def test_turbo_wrong_password_shows_the_login_page_again(self):
        turbo = {"HTTP_ACCEPT": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml"}
        r = self.client.post(reverse("login"), {"username": "arun", "password": "nope"}, **turbo)
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, "Employee Login", status_code=422)

    def test_pages_load_turbo_and_scripts_once_in_the_head(self):
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        html = self.client.get(reverse("dashboard")).content.decode()
        head = html.split("</head>")[0]
        self.assertIn("@hotwired/turbo", head)
        self.assertIn("js/app.js", head)
        self.assertNotIn("<script", html.split("</head>")[1])  # nothing re-run on every Turbo visit

    def test_project_form_has_member_search(self):
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        r = self.client.get(reverse("project_create"))
        self.assertContains(r, "data-member-search")
        self.assertContains(r, "data-member-count")
        self.assertContains(r, 'data-search="EMP')   # every row carries code / name / designation to search on
        self.assertContains(r, "Bulk7")

    def test_next_redirect_never_leaves_the_site(self):
        from .models import LeaveRequest, LeaveType

        self.assertTrue(self.client.login(username="hr", password="hr12345"))
        emp = Employee.objects.get(user__username="arun")
        from datetime import date as d, timedelta

        start = d.today() + timedelta(days=40)
        while start.weekday() >= 5:
            start += timedelta(days=1)
        leave = LeaveRequest.objects.create(employee=emp, leave_type=LeaveType.objects.first(), start_date=start,
                                            end_date=start)
        r = self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "reject", "next": "https://evil.example/"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example", r["Location"])
