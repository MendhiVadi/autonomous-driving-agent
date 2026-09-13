@echo off
setlocal
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
echo Presentation: Town04 with full scenery. No training or recording.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode presentation
pause
