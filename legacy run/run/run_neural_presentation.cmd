@echo off
setlocal
cd /d "%~dp0..\"
call "%~dp0..\scripts\environment.cmd"
if errorlevel 1 exit /b 1
"%CARLA_ROOT%\carla_env\Scripts\python.exe" -u "%~dp0..\app\neural_presentation.py" %*
exit /b %ERRORLEVEL%
