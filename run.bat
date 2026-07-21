@echo off
REM ============================================================
REM  CAGE EMPIRE - Windows launcher
REM  Run from project root:  C:\NEW CAGE EMPIRE\run.bat
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo [CAGE EMPIRE] Step 1/3 - Rebuild database...
python src\build_db.py
if errorlevel 1 (
    echo.
    echo [ERROR] build_db.py failed. Aborting.
    pause
    exit /b 1
)

echo.
echo [CAGE EMPIRE] Step 2/3 - Seed minimal world...
python src\seed_data.py
if errorlevel 1 (
    echo.
    echo [ERROR] seed_data.py failed. Aborting.
    pause
    exit /b 1
)

echo.
echo [CAGE EMPIRE] Step 3/3 - Launch app...
python src\app.py
if errorlevel 1 (
    echo.
    echo [ERROR] app.py failed.
    pause
    exit /b 1
)

endlocal
