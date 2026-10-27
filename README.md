# HR Portal - Django (Attendance, Employees, Projects)

Bright sky/ocean theme (water blue + orange, with an optional Dark mode button in the sidebar) web app (Django + Bootstrap 5 + CSS + JS + Turbo) with a **Tkinter desktop launcher**.
It is a **website only** (phone, tablet and desktop views) - the Flutter app was removed in v7.

## Screens (from the wireframe)
| Login type | Pages |
|---|---|
| Individual user | Home: department card, Present/Absent + **In Time / Out Time**, monthly attendance, **daily in/out history (today, yesterday, last 30 days)**, in-progress projects |
| HR / Admin | **Click any employee name** for full details (profile, today in/out, monthly attendance, projects, 30-day history; Back returns to the table). Home: employee table with **today's in/out time per employee** + Organization Snapshot + quick actions, **Employee** (add / edit / delete / search), **Project** (add / edit / delete, assign employees, status) |

Same header (company name + logo) on every page.

## v5 additions
Separate **Employee login** (`/login/`) and **Admin / HR login** (`/admin-login/`), unique employee codes, designations with permissions, leave credit + leave requests,
monthly / yearly filters, office vs field days, project completion % and project working days that subtract employee leave, `python manage.py check_db`.
See `RUN_GUIDE.md` (section 11) for the full list.

## Demo logins (created on first run)
| Role | Username | Password |
|---|---|---|
| Super Admin | `admin` | `admin123` |
| HR | `hr` | `hr12345` |
| Employee | `arun` / `priya` / `vijay` | `arun123` / `priya123` / `vijay123` |

Change these before using it for real.

## Quick start (VS Code)
1. Unzip, open the `hr_portal` folder in VS Code (needs Python 3.10+; Tkinter is included with the normal Python installer).
2. Open the VS Code terminal and run:

**Windows**
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run_desktop.py
```
(or just double-click `run.bat`)

**Mac / Linux**
```
./run.sh
```

`run_desktop.py` opens a small Tkinter window. It prepares the database, starts the server and
opens `http://127.0.0.1:8000/` in your browser. Use its buttons to Open / Stop the server.

### Without Tkinter (plain Django)
```
python manage.py makemigrations portal
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```
Run tests: `python manage.py test`

> The pages load Bootstrap from a CDN, so the first run needs internet access.

## Company name & logo
- Name: set `COMPANY_NAME` in `.env` (copy `.env.example` to `.env`).
- Logo: replace `static/img/logo.jpg` (keep the same file name). Login page photos: `static/img/bg-building1.jpg`, `bg-building2.jpg`.

## SQLite now -> PostgreSQL later
SQLite is the default (`db.sqlite3`). To switch, no code change is needed:
1. `pip install -r requirements-postgres.txt`
2. Create the database in PostgreSQL (`CREATE DATABASE hr_portal;`)
3. In `.env` set:
```
DB_ENGINE=postgres
DB_NAME=hr_portal
DB_USER=postgres
DB_PASSWORD=********
DB_HOST=127.0.0.1
DB_PORT=5432
```
4. `python manage.py migrate` then `python manage.py seed_demo`

(To move existing SQLite data: `python manage.py dumpdata --exclude contenttypes --exclude auth.permission > data.json`, switch DB, `migrate`, then `loaddata data.json`.)

## v7: faster, no full page reloads
- **Speed**: pages used to run one set of database queries *per employee* (Admin home ~150 queries). Now the
  whole team is loaded in a few batch queries (Admin home ~15, Attendance 7, Leave 8) - this matters a lot with a
  hosted PostgreSQL (Neon), where every query is a network round trip.
- **No page reload**: links, buttons and forms are handled by **Turbo** (loaded from a CDN). Only the content changes;
  header, sidebar and sea-wave background stay. Search boxes filter the table while you type. Month / year filters
  apply by themselves. After a button (Approve, Save update...) you stay at the same scroll position.
- **Project -> Members search**: type a name / code / designation / department / team, tick members, choose Office or
  Field. Buttons: *Selected only*, *Select shown*, *Clear*, and a live "N selected" counter.
- **Phone / tablet / desktop**: phone = top bar + card tables, tablet = slim sidebar, desktop = sticky sidebar.

## REST API (kept, not used by the website)
The `/api/` code (`portal/api.py`) is still inside the project but nothing in the website uses it. It can stay
dormant until a mobile app is needed again.

## Project structure
```
hr_portal/
  manage.py
  run_desktop.py        <- Tkinter launcher
  run.bat / run.sh      <- one-click setup + launch
  requirements.txt  requirements-postgres.txt  .env.example
  config/               <- settings (SQLite/PostgreSQL switch), urls
  portal/
    models.py           <- Department, Team, Employee, Attendance, Project, Leave ...
    middleware.py auth_backend.py     <- speed + Turbo support
    services.py         <- shared logic (clock in/out, monthly summary, roles)
    views.py forms.py urls.py        <- website
    api.py serializers.py api_urls.py <- REST API (not used by the website)
    management/commands/seed_demo.py
    templates/portal/   <- HTML (Bootstrap)
    tests.py
  static/ css/app.css  js/app.js  img/logo.jpg + bg-building*.jpg
```

## Production notes
Set `DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, run `collectstatic`,
and serve with gunicorn/nginx.

---

## PostgreSQL helper files

### `db/` folder (PostgreSQL)
| File | Purpose |
|---|---|
| `db/01_create_database.sql` | `CREATE DATABASE hr_portal` (+ optional app user) |
| `db/02_schema_postgres.sql` | All tables as plain SQL (old reference copy) |
| `db/03_useful_queries.sql` | Ready-made queries: today present/absent, monthly count, hours, projects... |

Recommended way to create the tables is `python manage.py migrate`. Check the connection with `python manage.py check_db`.
