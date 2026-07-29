@echo off
REM ============================================================
REM  CAGE EMPIRE - One-Click Launcher for Windows
REM
REM  Just double-click this file to play the game.
REM  It will:
REM    1. Check Python is installed
REM    2. Install required packages (first time only)
REM    3. Build the world database (first time only)
REM    4. Launch the game
REM
REM  Prerequisites: Python 3.10+ from https://python.org
REM  (Make sure "Add Python to PATH" is checked during install)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ================================================
echo   CAGE EMPIRE - One-Click Launcher
echo ================================================
echo.

REM --- Step 1: Check Python ---
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
echo   Python found: 
python --version
echo.

REM --- Step 2: Install packages (first time only) ---
echo [2/4] Checking required packages...
python -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo   Installing packages (first time only, may take a minute)...
    python -m pip install customtkinter pillow ttkbootstrap >nul 2>&1
    if errorlevel 1 (
        echo   [WARNING] Some packages failed to install. Trying with --user...
        python -m pip install --user customtkinter pillow ttkbootstrap >nul 2>&1
    )
    echo   Packages installed.
) else (
    echo   All packages already installed.
)
echo.

REM --- Step 3: Build world database (first time only) ---
echo [3/4] Checking game database...
if not exist "data\cage_empire.db" (
    echo   Building world database (first time only, takes ~10 seconds)...
    set CAGE_EMPIRE_ALLOW_FRESH=1
    python src\build_db.py --fresh
    python scripts\seed_world_phase1.py
    python scripts\seed_world_phase2.py
    python scripts\parse_fighter_profiles.py
    python scripts\assign_attributes_from_bios.py
    python scripts\seed_world_phase3_from_profiles.py
    python scripts\seed_world_phase4.py
    python scripts\seed_world_phase5.py
    python scripts\backfill_legends.py
    echo   World database built successfully!
) else (
    echo   Game database already exists.
)
echo.

REM --- Step 4: Launch the game ---
echo [4/4] Launching CAGE EMPIRE...
echo.
echo   The game window will open in a moment.
echo   Click "Advance Day" in the top bar to progress the simulation.
echo   Use the sidebar to navigate: Dashboard, Roster, Fighter Profile,
echo   Free Agents, Scouting, Save/Load.
echo.
echo   Close this window to quit (the game auto-saves on exit).
echo.
python src\app.py
if errorlevel 1 (
    echo.
    echo [ERROR] The game crashed. Check the error message above.
    pause
)
endlocal
