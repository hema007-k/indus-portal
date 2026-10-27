from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT id, employee_id, designation, department_id, user_id
        FROM portal_employee
        ORDER BY id
    """)
    for row in c.fetchall():
        print(row)
