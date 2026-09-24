@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manual.ps1" %*
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" echo Simulator stopped. Check this folder's logs.
exit /b %SESSION_EXIT%
