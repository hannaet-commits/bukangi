@echo off
REM Build a single-file exe with PyInstaller (inside the virtual environment).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_venv.bat

".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name Bukangi ^
    --add-data "assets;assets" ^
    main.py
if errorlevel 1 exit /b 1

echo.
echo Done: dist\Bukangi.exe
echo Tip: put an "assets" folder next to Bukangi.exe to override the bundled images.
pause
