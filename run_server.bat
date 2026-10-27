@echo off
rem Starts the portal WITHOUT the Tkinter launcher. Use this to open it on a phone (same Wi-Fi).
cd /d "%~dp0"
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt
if exist .env pip install -r requirements-postgres.txt
python manage.py migrate
python manage.py seed_demo
python manage.py check_db
echo.
echo ==============================================================
echo  Open on this PC : http://127.0.0.1:8000
echo  Open on a phone : http://YOUR-PC-IP:8000   (find it with: ipconfig)
echo  Employee login  : /login/        Admin / HR login : /admin-login/
echo ==============================================================
python manage.py runserver 0.0.0.0:8000
pause
