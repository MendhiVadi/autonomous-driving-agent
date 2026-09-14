@echo off
setlocal
cd /d "%~dp0..\"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" -u "%~dp0..\tools\validate_input_environment.py" %*
set "CHECK_EXIT=%ERRORLEVEL%"
pause
exit /b %CHECK_EXIT%
