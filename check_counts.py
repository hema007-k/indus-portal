from django.db import connection

tables = [
    "auth_user",
    "portal_department",
    "portal_employee",
    "portal_project",
    "portal_attendance",
    "portal_team",
]

with connection.cursor() as c:
    for table in tables:
        try:
            c.execute(f'SELECT COUNT(*) FROM "{table}"')
            print(f"{table}: {c.fetchone()[0]} records")
        except Exception as e:
            print(f"{table}: ERROR - {e}")
