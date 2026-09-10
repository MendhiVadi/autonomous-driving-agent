@echo off
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
if not defined DEVICE1_IP set "DEVICE1_IP=10.42.0.1"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" neural_drive_agent.py --carla-root "%CARLA_ROOT%" --host %DEVICE1_IP% --port 2000 --policy nn_policy.json --tick-timeout 2.0
pause
