@echo off
setlocal
cd /d "%~dp0..\"
call "%~dp0..\scripts\environment.cmd"
if errorlevel 1 exit /b 1
"%CARLA_ROOT%\carla_env\Scripts\python.exe" -u "%~dp0..\tools\validate_input_environment.py" %*
set "CHECK_EXIT=%ERRORLEVEL%"
pause
exit /b %CHECK_EXIT%
