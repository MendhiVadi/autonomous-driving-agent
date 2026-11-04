@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Lightweight neural driving. M opens the destination map; click a road. Driving keys take over.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode practice -CameraProfile map -RequireFreshServer -OpenMap %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Neural driving stopped. See the latest practice logs in logs.
pause
exit /b %SESSION_EXIT%
