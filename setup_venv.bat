@echo off
REM Create the virtual environment (.venv) and install dependencies.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment: .venv
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Please install Python 3.11+ and try again.
        pause
        exit /b 1
    )
) else (
    echo [1/3] .venv already exists.
)

echo [2/3] Upgrading pip
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo [3/3] Installing requirements.txt
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Install failed.
    pause
    exit /b 1
)

echo.
echo Done. Run run.bat to start Bukangi.
pause
