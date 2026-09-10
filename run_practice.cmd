@echo off
setlocal
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
echo Practice mode: live map and controls. Recording is OFF.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_practice.ps1" -CarlaRoot "%CARLA_ROOT%"
if errorlevel 1 echo Practice mode stopped because CARLA did not remain healthy.
pause
