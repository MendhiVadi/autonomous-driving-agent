@echo off
cd /d "%~dp0..\"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode training
pause
