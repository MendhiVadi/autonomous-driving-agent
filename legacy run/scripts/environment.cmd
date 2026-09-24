@echo off
rem Called inside each launcher's setlocal; retain an explicit CARLA_ROOT override.
if defined CARLA_ROOT exit /b 0
for /f "usebackq delims=" %%I in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0environment.ps1" -PrintCarlaRoot`) do set "CARLA_ROOT=%%I"
if not defined CARLA_ROOT (
    echo Unable to resolve CARLA_ROOT from config/runtime.json.
    exit /b 1
)
exit /b 0
