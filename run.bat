@echo off
REM Run Bukangi inside the virtual environment (no console window).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo .venv not found. Running setup_venv.bat first...
    call setup_venv.bat
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
