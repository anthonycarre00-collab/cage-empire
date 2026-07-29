@echo off
REM ============================================================
REM  CAGE EMPIRE - One-Click Launcher for Windows
REM
REM  Just double-click this file to play the game.
REM  Prerequisites: Python 3.10+ from https://python.org
REM  (Check "Add Python to PATH" during install)
REM ============================================================
cd /d "%~dp0"

echo.
echo ================================================
echo   CAGE EMPIRE - One-Click Launcher
echo ================================================
echo.

REM --- Step 1: Check Python ---
echo [1/4] Checking Python...
python --version 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
echo.

REM --- Step 2: Install packages ---
echo [2/4] Installing required packages...
echo   (If already installed, this will be quick)
python -m pip install customtkinter pillow ttkbootstrap
if %errorlevel% neq 0 (
    echo   Trying with --user flag...
    python -m pip install --user customtkinter pillow ttkbootstrap
)
echo   Done.
echo.

REM --- Step 3: Build world database (first time only) ---
echo [3/4] Checking game database...
if exist "data\cage_empire.db" (
    echo   Database already exists. Skipping build.
    goto LAUNCH
)

echo   Building world database (first time, takes ~15 seconds)...
echo.
set CAGE_EMPIRE_ALLOW_FRESH=1
python src\build_db.py --fresh
if %errorlevel% neq 0 (
    echo [ERROR] Database build failed.
    pause
    exit /b 1
)
python scripts\seed_world_phase1.py
python scripts\seed_world_phase2.py
python scripts\parse_fighter_profiles.py
python scripts\assign_attributes_from_bios.py
python scripts\seed_world_phase3_from_profiles.py
python scripts\seed_world_phase4.py
python scripts\seed_world_phase5.py
python scripts\backfill_legends.py
echo.
echo   World database built!
echo.

:LAUNCH
REM --- Step 4: Launch the game ---
echo [4/4] Launching CAGE EMPIRE...
echo.
echo   TIP: Click "Advance Day" (gold button, top-right) to play.
echo   Use the sidebar to browse Roster, Fighter Profile, Free Agents, etc.
echo   The game auto-saves when you close the window.
echo.
python src\app.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The game encountered an error. See message above.
    pause
)
