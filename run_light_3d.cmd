@echo off
setlocal
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
echo Lightweight 3D driving: Town02, one front camera, clear weather and reduced scenery.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -LowScenery
if errorlevel 1 echo The 3D session stopped. Check the latest practice logs.
pause
