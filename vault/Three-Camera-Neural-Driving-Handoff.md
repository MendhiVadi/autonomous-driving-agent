# Three-Camera Neural Driving Handoff

Updated: 2026-10-06 (after testing). The working code is in `legacy run/`; this note is copied to both project vaults.

## Goal

Get the existing one-laptop CARLA setup running with clear front, left and right camera feeds, working manual controls, the saved neural model and its local activity page. Then verify Town13 separately. Keep thermal checks, collision sensing, watchdog braking and neural safety arbitration enabled.

## Status (2026-10-06, updated after testing)

Verified on Town02_Opt in bounded, launcher-started runs; details in [[Session-Log]]:

- Three Epic offscreen cameras now run for minutes under **DX12** with the cockpit ticking CARLA at 15 Hz; DX11 hangs on any RGB camera. Camera profiles default to DX12.
- Side-feed corruption was a GPU row-alignment effect for 240 px widths; widths are now multiples of 64 (256x144).
- Scripted key replay confirmed W/S/A/D, arrow and Space controls reach CARLA and move the car; the HUD no longer shows a CARLA-view banner or manual-gear warnings in automatic neural mode.
- The neural model drove routes with safety arbitration active (red-light stop observed); route alignment was broken twice over, fixed, and then realigned a car rotated 180 degrees before it drove to the destination. The activity page updates.
- A car stuck off its route ("MODEL STOP - REALIGN MANUALLY", seen on Town13) now recovers itself after a 3 s on-screen countdown; the activity page shows the same countdown as a yellow line.
- Town13 loads, streams, runs the cameras and shuts down cleanly; it drove a straight 120 m route but stopped at a sharp corner twice. Still experimental.

## Still open

1. **Real keyboard focus** is unverified: click the cockpit, hold W then A/D, S, arrows, Space, and confirm the status line shows `LIVE INPUT` and the car responds. (Computer-use access to the window was declined, so nothing injected OS input.)
2. Town13 sharp corners; start assist caps the cruise speed near 15.8 km/h; GPU load is high and cockpit FPS fell across back-to-back runs.
3. A 100 s neural route stops at waypoint 131/140 only because of the time cap; nothing here proves general autonomy.

## Files to review

- `legacy run/run_graphics_neural.cmd`
- `legacy run/run_large_map_neural.cmd`
- `legacy run/scripts/run_practice.ps1`
- `legacy run/app/cockpit/options.py`
- `legacy run/app/cockpit/session.py`
- `legacy run/app/cockpit/viewport_input.py`
- `legacy run/app/cockpit/hud.py`, `navigation.py`, `world.py`, `graphics.py`
- `legacy run/docs/CRASH_DIAGNOSIS.md` and `legacy run/tools/render_probe.py` (DX11/DX12 evidence)

