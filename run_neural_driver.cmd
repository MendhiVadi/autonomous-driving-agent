@echo off
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" neural_drive_agent.py --carla-root "%CARLA_ROOT%" --policy nn_policy_colab.json --tick-timeout 2.0
pause
