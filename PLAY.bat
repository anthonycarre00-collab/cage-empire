@echo off
REM ============================================================
REM  CAGE EMPIRE - One-Click Launcher for Windows
REM
REM  The game database (data\cage_empire.db) ships with the game.
REM  No building or seeding needed — just install packages and play.
REM
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
echo [1/3] Checking Python...
python --version 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
echo.

REM --- Step 2: Install packages (if not already installed) ---
echo [2/3] Checking required packages...
python -c "import customtkinter" 2>nul
if %errorlevel% neq 0 (
    echo   Installing packages (one-time setup, may take a minute)...
    python -m pip install customtkinter pillow ttkbootstrap
    if %errorlevel% neq 0 (
        echo   Trying with --user flag...
        python -m pip install --user customtkinter pillow ttkbootstrap
    )
    echo   Packages installed.
) else (
    echo   All packages already installed.
)
echo.

REM --- Step 3: Launch the game ---
echo [3/3] Launching CAGE EMPIRE...
echo.
echo   TIP: Click "Advance Day" (gold button, top-right) to play.
echo   Use the sidebar to browse Roster, Fighter Profile, Free Agents, etc.
echo   The game auto-saves when you close the window.
echo.
python src\app.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The game encountered an error.
    echo If this is the first run, make sure packages installed correctly above.
    echo.
    pause
)
