"""python manage.py check_db  -> verifies the database connection and that data is saved / read back correctly."""
import uuid
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from portal.models import (
    Attendance, Department, Designation, Employee, LeaveRequest, LeaveType, Project, Team,
)

User = get_user_model()


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Check the database connection (SQLite / PostgreSQL / Neon) and run a save-and-read-back test."

    def handle(self, *args, **opts):
        s = connection.settings_dict
        self.stdout.write(f"Engine   : {connection.vendor}  ({s['ENGINE']})")
        self.stdout.write(f"Database : {s.get('NAME')}")
        if connection.vendor == "postgresql":
            self.stdout.write(f"Host     : {s.get('HOST')}:{s.get('PORT') or 5432}   User: {s.get('USER')}")

        # 1. connection
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT version()" if connection.vendor == "postgresql" else "SELECT sqlite_version()")
                self.stdout.write(self.style.SUCCESS(f"[PASS] Connected. Server: {cur.fetchone()[0]}"))
        except Exception as exc:  # noqa: BLE001 - show whatever the driver says
            raise CommandError(f"[FAIL] Cannot connect to the database: {exc}")

        # 2. migrations
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            raise CommandError(f"[FAIL] {len(pending)} migration(s) not applied. Run:  python manage.py migrate")
        self.stdout.write(self.style.SUCCESS("[PASS] All migrations are applied."))

        # 3. save + read back in one transaction, rolled back afterwards (your data is not touched)
        suffix = uuid.uuid4().hex[:6]
        try:
            with transaction.atomic():
                dept = Department.objects.create(name=f"check-dept-{suffix}")
                team = Team.objects.create(name=f"check-team-{suffix}", department=dept)
                desig = Designation.objects.create(name=f"check-desig-{suffix}")
                user = User.objects.create_user(f"check_{suffix}", password="x", first_name="Check")
                emp = Employee.objects.create(user=user, department=dept, team=team, designation=desig)
                Attendance.objects.create(employee=emp, date=date(2026, 1, 5), in_time=time(9, 5),
                                          out_time=time(18, 10), work_mode="field")
                ltype = LeaveType.objects.first() or LeaveType.objects.create(name=f"check-leave-{suffix}")
                LeaveRequest.objects.create(employee=emp, leave_type=ltype, start_date=date(2026, 1, 6),
                                            end_date=date(2026, 1, 8), status="approved")
                proj = Project.objects.create(name=f"check-proj-{suffix}", completion=40)
                proj.employees.set([emp])

                got = Employee.objects.select_related("designation", "team").get(pk=emp.pk)
                att = got.attendance.get()
                leave = got.leaves.get()
                checks = {
                    "employee code generated": bool(got.employee_id),
                    "designation saved": got.designation_id == desig.pk,
                    "team saved": got.team.name == team.name,
                    "attendance in/out/mode saved": (att.in_time, att.out_time, att.work_mode) == (time(9, 5), time(18, 10), "field"),
                    "leave working days = 3": leave.days == 3,
                    "project employees + completion saved": got.projects.get().completion == 40,
                }
                for label, ok in checks.items():
                    (self.stdout.write(self.style.SUCCESS(f"[PASS] {label}")) if ok
                     else self.stdout.write(self.style.ERROR(f"[FAIL] {label}")))
                if not all(checks.values()):
                    raise CommandError("Some save/read checks failed.")
                raise Rollback  # undo the test rows
        except Rollback:
            pass
        self.stdout.write(self.style.SUCCESS("[PASS] Test rows were rolled back - nothing was added to your data."))

        # 4. what is in there now
        for model in (Department, Team, Designation, Employee, Attendance, Project, LeaveType, LeaveRequest):
            self.stdout.write(f"  {model.__name__:<13}: {model.objects.count()} row(s)")
        self.stdout.write(self.style.SUCCESS("\nDatabase OK."))
