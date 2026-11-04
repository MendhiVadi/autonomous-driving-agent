@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Town13 with Epic graphics, three cameras, the existing neural policy and activity website.
echo Drive with W/A/S/D in the cockpit. M opens the destination map; click a road for neural driving.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode practice -Map Town13 -CameraProfile triple -FullGraphics -RequireFreshServer %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Town13 neural session stopped. See the latest practice logs in logs.
pause
exit /b %SESSION_EXIT%
