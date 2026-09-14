@echo off
setlocal
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
echo Training data: 12 BasicAgent routes on Town02. Graphics and cameras are OFF.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode expert
set "SESSION_EXIT=%ERRORLEVEL%"
pause
exit /b %SESSION_EXIT%
