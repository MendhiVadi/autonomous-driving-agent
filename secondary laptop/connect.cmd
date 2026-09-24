@echo off
setlocal
if "%~1"=="" (
    echo Usage: connect.cmd PRIMARY_IP
    echo Runs five brake-held simulation steps over the paired encrypted connection. No training.
    exit /b 2
)
python -I -B "%~dp0diagnose.py" --tls --host "%~1" --steps 5
exit /b %ERRORLEVEL%
