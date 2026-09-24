# Two driving modes

## Controls

`run_car.cmd`: click the CARLA window. W/S or Up/Down accelerate/brake,
A/D or Left/Right steer, Space handbrake, R changes forward/reverse while
stopped, C switches chase/bonnet view, Esc exits. Losing focus brakes the car.
Graphics use Town02_Opt with all scenery, Epic quality, wind 65 and a 30 FPS
cap at 1280 x 720. No additional cars are spawned.

`run_neural.cmd`: the destination map opens immediately; click a road to drive
there. M reopens it.
Driving keys take over; Esc closes the map, then exits. F8 reopens network
activity. `-NoNeuralVisual` skips the browser. Existing assistance and safety
arbitration remain active; this is a preliminary assisted model.

Run one mode at a time. Both commands accept PowerShell launcher options,
including `-Map Town05`, `-RenderApi dx12`, and `-MaxRuntimeSeconds 30`.
Close the current CARLA session before switching graphics profiles.

Epic/Low and disabled rendering follow the
[CARLA rendering documentation](https://carla.readthedocs.io/en/latest/adv_rendering_options/).
Wind animation depends on the map's foliage materials.

## Changes and verification

- The trained network and its normalization remain unchanged. The runtime
  reuses the parsed map instead of fetching it again during each observation.
- Maps now sample lane curves, keep a spatial index for nearby roads and cache
  the full-town background. The destination map also shows the remaining route.
- Optimized-map scenery is unloaded in neural mode even when already on the
  selected map. The launcher checks policy validity before starting CARLA.
- Actor queries are shared, changing-control logs are limited to 4 Hz (input,
  focus, gear and emergency-brake transitions remain immediate), and model
  loading is excluded from runtime FPS reports.
- Owned shipping processes are remembered for cleanup if the bootstrap exits.

Live verification on 2026-09-19: a 35-second full-graphics session showed the
native scene and car, logged 28.8-29.7 FPS, forward movement up to 48.7 km/h
and reverse movement, then exited cleanly. A 90-second neural session loaded
976 sampled map segments, opened its activity page and destination map,
accepted a 203 m route and drove under the saved network with labelled
assistance. A read-only RPC check confirmed rendering disabled and zero RGB
cameras; normal update rates were approximately 19-20 FPS. The time-limited
trial ended before completing the route, so this does not establish route
completion or general autonomous-driving performance.

Offline verification: all 159 regression tests passed after the simulator
closed. Every activation in the saved live neural snapshot matched a fresh
forward pass through the existing weights exactly. PowerShell parsing passed,
and no CARLA or driving-client processes remained after the bounded trials.
