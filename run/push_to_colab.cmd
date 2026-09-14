@echo off
setlocal
cd /d "%~dp0..\"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" tools\push_to_colab.py
set "UPLOAD_RESULT=%ERRORLEVEL%"
if not "%UPLOAD_RESULT%"=="2" exit /b %UPLOAD_RESULT%
echo Please finish the Google authorization page that opens.
call "%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" auth login --enable-gdrive-access --force --brief
if errorlevel 1 exit /b 1
"%CARLA_ROOT%\carla_env\Scripts\python.exe" tools\push_to_colab.py
exit /b %ERRORLEVEL%
