The tables are created by Django, not by these files:

    python manage.py migrate

02_schema_postgres.sql is only an old reference copy of the first version of the schema
(it does not have designations, leave, work mode, project completion).
Use  python manage.py check_db  to verify the PostgreSQL / Neon connection.
