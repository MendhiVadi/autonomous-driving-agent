@echo off
cd /d "%~dp0..\"
call "%~dp0..\scripts\environment.cmd"
if errorlevel 1 exit /b 1
"%CARLA_ROOT%\carla_env\Scripts\python.exe" app\neural_drive_agent.py --carla-root "%CARLA_ROOT%" --policy nn_policy_colab.json --tick-timeout 2.0
pause
