@echo off
:: start_hostel.bat — Windows shortcut to start BioSecure AI Girls Hostel Security System

title BioSecure AI - Girls Hostel Management System

cd /d "%~dp0"

echo =================================================================
echo   BioSecure AI — Girls Hostel Security ^& Management System
echo =================================================================

:: Activate virtual environment if available
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo Creating Python virtual environment (.venv)...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installing dependencies...
    if exist requirements-windows.txt (
        pip install -r requirements-windows.txt
    ) else (
        pip install -r requirements.txt
    )
)

if not exist .env (
    if exist .env.example (
        echo Copying .env.example to .env...
        copy .env.example .env
    )
)

echo Starting BioSecure AI Girls Hostel server on http://localhost:5000...
python app.py %*
pause

