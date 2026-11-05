@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Neural driving - large map (Town13), three-camera cockpit
echo  Town13 needs the CARLA AdditionalMaps package and takes a few
echo  minutes to load. Same controls as run_neural.cmd: click a
echo  road on the map, M map, F8 network page, Backspace reset,
echo  Esc exit. Treat long routes as experimental.
echo ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Mode neural -Map Town13 %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Town13 neural driving stopped with an error. See the newest files in the logs folder.
pause
exit /b %SESSION_EXIT%
