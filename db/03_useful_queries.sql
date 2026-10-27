-- =====================================================================
-- Daily use ku useful queries (pgAdmin Query Tool la copy/paste panni run pannunga)
-- Ellaame hr_portal DB la, Django tables mela run aagum.
-- =====================================================================

-- 1. Ella tables um paakka
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;

-- 2. Ella employees (login username, department, team oda)
SELECT e.id, e.employee_id, u.username, u.first_name || ' ' || u.last_name AS full_name,
       e.role, e.status, d.name AS department, t.name AS team, e.designation
FROM portal_employee e
JOIN auth_user u            ON u.id = e.user_id
LEFT JOIN portal_department d ON d.id = e.department_id
LEFT JOIN portal_team t       ON t.id = e.team_id
ORDER BY e.employee_id;

-- 3. Indha naal yaar yaar present (in / out time)
SELECT e.employee_id, u.first_name AS name, a.in_time, a.out_time
FROM portal_attendance a
JOIN portal_employee e ON e.id = a.employee_id
JOIN auth_user u       ON u.id = e.user_id
WHERE a.date = CURRENT_DATE
ORDER BY a.in_time;

-- 4. Indha naal absent (active employees la attendance illaadhavanga)
SELECT e.employee_id, u.first_name AS name
FROM portal_employee e
JOIN auth_user u ON u.id = e.user_id
WHERE e.status = 'active'
  AND NOT EXISTS (SELECT 1 FROM portal_attendance a
                  WHERE a.employee_id = e.id AND a.date = CURRENT_DATE);

-- 5. Indha maasam ovvoru employee oda present days
SELECT e.employee_id, u.first_name AS name, COUNT(a.id) AS present_days
FROM portal_employee e
JOIN auth_user u ON u.id = e.user_id
LEFT JOIN portal_attendance a
       ON a.employee_id = e.id
      AND date_trunc('month', a.date) = date_trunc('month', CURRENT_DATE)
GROUP BY e.employee_id, u.first_name
ORDER BY e.employee_id;

-- 6. Oru employee oda working hours (last 30 days)
SELECT a.date, a.in_time, a.out_time,
       (a.out_time - a.in_time) AS worked
FROM portal_attendance a
JOIN portal_employee e ON e.id = a.employee_id
WHERE e.employee_id = 'EMP003'
  AND a.date >= CURRENT_DATE - 30
ORDER BY a.date DESC;

-- 7. Projects + assign aana employees
SELECT p.id, p.name, p.status, STRING_AGG(e.employee_id, ', ' ORDER BY e.employee_id) AS team_members
FROM portal_project p
LEFT JOIN portal_project_employees pe ON pe.project_id = p.id
LEFT JOIN portal_employee e           ON e.id = pe.employee_id
GROUP BY p.id, p.name, p.status
ORDER BY p.id DESC;

-- 8. Department wise employee count
SELECT d.name AS department, COUNT(e.id) AS employees
FROM portal_department d
LEFT JOIN portal_employee e ON e.department_id = d.id
GROUP BY d.name ORDER BY employees DESC;

-- 9. Employee ah inactive aakka (login um block aagum - is_active=false)
-- UPDATE portal_employee SET status = 'inactive' WHERE employee_id = 'EMP005';
-- UPDATE auth_user SET is_active = FALSE
--  WHERE id = (SELECT user_id FROM portal_employee WHERE employee_id = 'EMP005');
-- Prefer: app / Django admin la maathunga (password hash, token ellam sariya handle aagum).

-- 10. Database size
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;
