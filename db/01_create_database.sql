-- =====================================================================
-- STEP 1 : Database create panna (pgAdmin / psql la 'postgres' DB la run pannunga)
-- =====================================================================
-- psql la:   psql -U postgres -h 127.0.0.1 -f db/01_create_database.sql

CREATE DATABASE hr_portal
    WITH ENCODING 'UTF8'
         TEMPLATE template0;

-- (Optional) app ku thani user - production la 'postgres' superuser use pannaadheenga
-- CREATE USER hr_user WITH PASSWORD 'ChangeThisPassword';
-- GRANT ALL PRIVILEGES ON DATABASE hr_portal TO hr_user;
-- \c hr_portal
-- GRANT ALL ON SCHEMA public TO hr_user;
