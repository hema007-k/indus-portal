from django.db import connection
with connection.cursor() as c:
    c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
    for row in c.fetchall():
        print(row[0])
