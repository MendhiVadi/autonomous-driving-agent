@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Neural driving - small map (Town02_Opt), three-camera cockpit
echo  The destination map opens first: click a road and the network
echo  drives there. M reopens the map, F8 opens the network activity
echo  page, any driving key (W/A/S/D, arrows, Space) takes over,
echo  Backspace resets the car, Esc exits.
echo  Slow PC?  run_neural.cmd -Lightweight   (map cockpit, no cameras)
echo ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Mode neural %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Neural driving stopped with an error. See the newest files in the logs folder.
pause
exit /b %SESSION_EXIT%
