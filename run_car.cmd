@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Manual car - full graphics (Town02_Opt, Epic quality)
echo  Click the CARLA window, then: W/S or Up/Down accelerate/brake,
echo  A/D or Left/Right steer, Space handbrake, R reverse (when
echo  stopped), C chase/bonnet view, Esc exit.
echo ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Mode manual %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Driving stopped with an error. See the newest files in the logs folder.
pause
exit /b %SESSION_EXIT%
