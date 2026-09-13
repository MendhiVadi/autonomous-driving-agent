@echo off
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" collect_expert_data.py --carla-root "%CARLA_ROOT%" --map Town05 --output-dir episodes/expert --episodes 12
pause
