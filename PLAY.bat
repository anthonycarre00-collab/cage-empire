@echo off
cd /d "%~dp0"

echo.
echo ================================================
echo   CAGE EMPIRE - One-Click Launcher
echo ================================================
echo.

REM === Step 1: Find Python ===
echo [1/3] Finding Python...

python --version 2>nul
if %errorlevel%==0 goto FOUND_PYTHON

py --version 2>nul
if %errorlevel%==0 goto FOUND_PY

python3 --version 2>nul
if %errorlevel%==0 goto FOUND_PYTHON3

echo.
echo [ERROR] Could not find Python. Tried: python, py, python3
echo.
echo Please install Python 3.10+ from https://python.org
echo During install, make sure "Add Python to PATH" is checked.
echo.
pause
exit /b 1

:FOUND_PYTHON
set PYCMD=python
goto INSTALL_PACKAGES

:FOUND_PY
set PYCMD=py
goto INSTALL_PACKAGES

:FOUND_PYTHON3
set PYCMD=python3
goto INSTALL_PACKAGES

:INSTALL_PACKAGES
echo.
echo [2/3] Installing required packages...
echo   (If already installed, this will be very quick)
echo.

%PYCMD% -m pip install customtkinter pillow ttkbootstrap
if %errorlevel%==0 goto PACKAGES_OK

echo.
echo   First attempt failed. Trying with --user flag...
%PYCMD% -m pip install --user customtkinter pillow ttkbootstrap
if %errorlevel%==0 goto PACKAGES_OK

echo.
echo [ERROR] Could not install packages.
echo   Try running this manually:
echo   %PYCMD% -m pip install customtkinter pillow ttkbootstrap
echo.
pause
exit /b 1

:PACKAGES_OK
echo.
echo   Packages OK.
echo.

REM === Step 3: Launch ===
echo [3/3] Launching CAGE EMPIRE...
echo.
echo   TIP: Click Advance Day (gold button, top-right) to play.
echo   Use the sidebar to browse your promotion.
echo   The game auto-saves when you close the window.
echo.
echo   If an error appears below, take a screenshot and report it.
echo.

%PYCMD% src\app.py

echo.
echo ================================================
echo   Game closed. (If there was an error, it's above)
echo ================================================
echo.
pause
