@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Full scenery, one manual car. Click CARLA: WASD drive, Space brake, R reverse, C view, Esc exit.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode scenic -RequireFreshServer %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Driving stopped. See the latest scenic logs in logs.
pause
exit /b %SESSION_EXIT%
