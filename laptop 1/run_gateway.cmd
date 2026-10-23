@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manual.ps1" -Mode gateway %*
exit /b %ERRORLEVEL%
