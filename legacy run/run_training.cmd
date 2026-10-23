@echo off
setlocal
cd /d "%~dp0"
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Legacy imitation-learning data collection, not RL training.
echo Training data: 12 BasicAgent routes on Town02. Graphics and cameras are OFF.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode expert %*
set "SESSION_EXIT=%ERRORLEVEL%"
pause
exit /b %SESSION_EXIT%
