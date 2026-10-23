# Three-Camera Neural Driving Handoff

Updated: 2026-10-06. The working code is in `legacy run/`; this note is copied to both project vaults.

## Goal

Get the existing one-laptop CARLA setup running with clear front, left and right camera feeds, working manual controls, the saved neural model and its local activity page. Then verify Town13 separately. Keep thermal checks, collision sensing, watchdog braking and neural safety arbitration enabled.

## Work completed

- Added the `triple` camera profile and focused-window input helper.
- Changed both neural graphics launchers to open the three-camera cockpit. Press **M** and click a road to start neural route driving.
- Kept the existing route-conditioned model and local activity page. Added stationary alignment when the selected route points substantially away from the car.
- Reduced display size/rate for three-camera graphics and adjusted the graphics control lease.
- Tried bounded Town02_Opt graphics runs. Evidence is under `legacy run/logs/`.

## Remaining work

1. Run `legacy run/run_graphics_neural.cmd` on Town02_Opt. Confirm all three feeds stay clear, the webpage updates, the simulator remains responsive, and shutdown restores the world cleanly.
2. Fix or isolate any CARLA RPC/render stall. Earlier native-window plus camera testing stalled. One screenshot showed corrupted side feeds; frame copying was changed but needs verification.
3. Test manual W/A/S/D and arrow controls, including throttle, brake, steering, focus cues and gear display.
4. Select a destination with **M**. Confirm alignment, model movement, route progress and safety interventions.
5. Test Town13 only after Town02 is stable. Record load time, camera frame rates, route progress and clean shutdown; Town13 remains experimental.
6. Update the root README and dated vault notes with verified results. Startup alone is not a passing driving test.

## Test evidence and limits

- A Town02 run loaded all three sensors, the model, route graph and browser page. It briefly moved at about 5.4 km/h, then stopped responding during graphics calls; sustained driving is unverified.
- Route alignment was added after a Town13 log showed the car facing about 175 degrees away from the planned road. Its effect on a complete route is unverified.
- Epic three-camera rendering was changed to offscreen mode to avoid the extra native viewport load. The test was interrupted before completion.
- Thermal and hardware protections remain enabled. Local CARLA testing does not require Wi-Fi.

## Files to review

- `legacy run/run_graphics_neural.cmd`
- `legacy run/run_large_map_neural.cmd`
- `legacy run/scripts/run_practice.ps1`
- `legacy run/app/cockpit/options.py`
- `legacy run/app/cockpit/session.py`
- `legacy run/app/cockpit/viewport_input.py`

