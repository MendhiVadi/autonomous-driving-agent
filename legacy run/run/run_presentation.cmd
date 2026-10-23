@echo off
setlocal
cd /d "%~dp0..\"
call "%~dp0..\scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Presentation: Town04 with full scenery. No training or recording.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -Mode presentation
pause
