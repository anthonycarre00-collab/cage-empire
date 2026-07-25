@echo off
REM ============================================================
REM  CAGE EMPIRE - Windows launcher + build tool
REM
REM  Usage:
REM    run.bat                Launch the game (uses existing DB)
REM    run.bat build-world    Full world rebuild (phase 1-5, ~10s, 4900+ fighters)
REM    run.bat build-dev      Minimal dev rebuild (5 fighters for testing)
REM    run.bat migrate        Apply schema migrations to existing DB (preserves world)
REM    run.bat check          Forensic DB integrity check
REM    run.bat test           Run all 38 acceptance tests
REM    run.bat backfill       Backfill retired legends' attributes
REM
REM  Run from project root:  run.bat ^<mode^>
REM ============================================================
setlocal
cd /d "%~dp0"

set PYTHON=python
set MODE=%1
if "%MODE%"=="" set MODE=run

if "%MODE%"=="run" goto run
if "%MODE%"=="build-world" goto build-world
if "%MODE%"=="build-dev" goto build-dev
if "%MODE%"=="migrate" goto migrate
if "%MODE%"=="check" goto check
if "%MODE%"=="test" goto test
if "%MODE%"=="backfill" goto backfill
goto usage

:run
echo [CAGE EMPIRE] Launching game...
%PYTHON% src\app.py
if errorlevel 1 (
    echo.
    echo [ERROR] app.py failed.
    pause
    exit /b 1
)
goto end

:build-world
echo [CAGE EMPIRE] Full world rebuild (DESTROYS existing DB)...
echo.
echo Step 1/7: Fresh build (schema only)...
%PYTHON% src\build_db.py --fresh
if errorlevel 1 goto error
echo.
echo Step 2/7: World seed phase 1 (nations, regions, cities, venues, weight classes, names)...
%PYTHON% scripts\seed_world_phase1.py
if errorlevel 1 goto error
echo.
echo Step 3/7: World seed phase 2 (gyms, promotions, staff)...
%PYTHON% scripts\seed_world_phase2.py
if errorlevel 1 goto error
echo.
echo Step 4/7: World seed phase 3 (4900 fighters)...
%PYTHON% scripts\seed_world_phase3.py
if errorlevel 1 goto error
echo.
echo Step 5/7: World seed phase 4 (career histories, fights, titles, contracts)...
%PYTHON% scripts\seed_world_phase4.py
if errorlevel 1 goto error
echo.
echo Step 6/7: World seed phase 5 (bios, gym histories, retired legends, news)...
%PYTHON% scripts\seed_world_phase5.py
if errorlevel 1 goto error
echo.
echo Step 7/7: Backfill retired legends' attributes...
%PYTHON% scripts\backfill_legends.py
if errorlevel 1 goto error
echo.
echo [CAGE EMPIRE] World rebuild complete.
echo Run 'run.bat check' to verify DB integrity.
goto end

:build-dev
echo [CAGE EMPIRE] Minimal dev rebuild (5 fighters)...
%PYTHON% src\build_db.py --fresh
if errorlevel 1 goto error
%PYTHON% src\seed_data.py
if errorlevel 1 goto error
echo [CAGE EMPIRE] Dev rebuild complete.
goto end

:migrate
echo [CAGE EMPIRE] Applying schema migrations (preserves world data)...
echo Backing up DB first...
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set TIMESTAMP=%dt:~0,8%-%dt:~8,6%
copy data\cage_empire.db "data\cage_empire.db.backup-%TIMESTAMP%"
%PYTHON% src\build_db.py --migrate
if errorlevel 1 goto error
echo [CAGE EMPIRE] Migration complete.
echo Run 'run.bat check' to verify DB integrity.
goto end

:check
echo [CAGE EMPIRE] Forensic DB integrity check...
%PYTHON% scripts\forensic_db_check.py --verbose
goto end

:test
echo [CAGE EMPIRE] Running all acceptance tests...
set PASS=0
set FAIL=0
for %%f in (scripts\test_*.py) do (
    %PYTHON% %%f > NUL 2>&1
    if errorlevel 1 (
        echo   FAIL  %%~nxf
        set /a FAIL+=1
    ) else (
        echo   PASS  %%~nxf
        set /a PASS+=1
    )
)
echo.
echo Results: %PASS% pass / %FAIL% fail
goto end

:backfill
echo [CAGE EMPIRE] Backfilling retired legends' attributes...
%PYTHON% scripts\backfill_legends.py
if errorlevel 1 goto error
echo [CAGE EMPIRE] Backfill complete.
goto end

:usage
echo Usage: run.bat [run^|build-world^|build-dev^|migrate^|check^|test^|backfill]
echo.
echo   run          Launch the game (default)
echo   build-world  Full world rebuild (4900+ fighters, ~10s)
echo   build-dev    Minimal dev rebuild (5 fighters for testing)
echo   migrate      Apply schema migrations (preserves world data)
echo   check        Forensic DB integrity check
echo   test         Run all 38 acceptance tests
echo   backfill     Backfill retired legends' attributes
exit /b 1

:error
echo.
echo [ERROR] Build step failed. Aborting.
pause
exit /b 1

:end
endlocal
