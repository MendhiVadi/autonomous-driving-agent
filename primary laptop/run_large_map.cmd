@echo off
setlocal
call "%~dp0run_manual.cmd" -Map Town13 %*
exit /b %ERRORLEVEL%
