@echo off
setlocal
call "%~dp0scripts\environment.cmd"
if errorlevel 1 exit /b 1
"%CARLA_ROOT%\carla_env\Scripts\python.exe" "%~dp0tools\verify.py"
exit /b %errorlevel%
