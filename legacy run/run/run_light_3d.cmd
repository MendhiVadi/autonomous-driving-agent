@echo off
setlocal
cd /d "%~dp0..\"
call "%~dp0..\scripts\environment.cmd"
if errorlevel 1 exit /b 1
echo Lightweight 3D driving: Town02, one front camera, clear weather and reduced scenery.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\run_practice.ps1" -CarlaRoot "%CARLA_ROOT%" -LowScenery
if errorlevel 1 echo The 3D session stopped. Check the latest practice logs.
pause
