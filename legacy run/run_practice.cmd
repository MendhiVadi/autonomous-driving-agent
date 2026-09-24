@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Loading the small map and neural network. Press M, then click a road to try driving there.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" %*
set "SESSION_EXIT=%ERRORLEVEL%"
if errorlevel 1 echo Practice mode stopped because CARLA did not remain healthy.
pause
exit /b %SESSION_EXIT%
