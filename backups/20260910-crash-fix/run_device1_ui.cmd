@echo off
cd /d "%~dp0"
if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%CARLA_ROOT%\carla_env\Scripts\python.exe" "%CARLA_ROOT%\spawn_car.py" --map Town04 --camera-profile parking --window-width 1280 --window-height 720 --target-fps 30 --camera-fps 8 --mirror-camera-fps 4 --input-latch-ms 35 --route-speed-kmh 45 --route-policy "%~dp0nn_policy_colab.json" --graphics-throttle-start-kmh 70 --graphics-speed-cap-kmh 90 --visual-austerity-start-kmh 38 --visual-austerity-resume-kmh 32 --runtime-rpc-timeout 2 --screenshot-path "%~dp0cockpit_last_frame.png"
pause
