@echo off
setlocal
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" "%~dp0tools\verify.py"
exit /b %errorlevel%
