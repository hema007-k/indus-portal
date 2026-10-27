from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'portal_employee'
        ORDER BY ordinal_position
    """)
    for row in c.fetchall():
        print(row)
