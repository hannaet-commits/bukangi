@echo off
REM Test mode: shows a console log and adds animation test items to the right-click menu.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_venv.bat
".venv\Scripts\python.exe" main.py --test --multi %*
pause
