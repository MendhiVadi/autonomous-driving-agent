# Two driving modes

Implementation plan (2026-09-19):

1. Keep the existing trained contract-v2 policy, training data and safety supervisor.
2. Add `run_car.cmd`: one manual car, native CARLA viewport, Epic scenery,
   animated wind, no neural model, browser, RGB sensors or extra cockpit.
3. Add `run_neural.cmd`: Town02_Opt, no scene rendering, fixed 20 Hz physics,
   the existing neural controller and destination map. Keep practice compatible.
4. Sample actual lane curves once, index nearby map segments, cache the town
   background and reuse the parsed CARLA map during inference.
5. Reject overlapping sessions, validate weights before simulator startup,
   clean up owned processes, run offline regressions and bounded live trials.

The pre-change source is preserved by Git HEAD; the working tree was clean.
The existing Finish R1 backup and datasets are untouched.

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

Live outputs are in `logs/scenic-20260919-162905-driving.log`, the September 19
practice cockpit log, `logs/practice-map.png` and
`logs/two-modes-live-neural.json`. Desktop automation was stopped when the
physical Escape key was pressed; no further desktop input was sent.
