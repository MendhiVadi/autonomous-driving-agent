# Autonomous driving agent workspace

The current CARLA installation is at:

`C:\Users\medha\Documents\CARLA\CARLA_0.9.16`

## Current stable manual driving (2026-09-10)

Run `run_practice.cmd` (or `run_device1_ui.cmd`) for the live map and manual
controls. This starts one off-screen CARLA server, disables scene rendering
with `WorldSettings.no_rendering_mode`, and creates no RGB cameras. Physics,
road geometry, nearby actors, gears, speed/RPM instruments, and the `M`
destination map remain available. Recording is off. Closing the window stops
an owned server; an existing healthy server is preserved. Logs are saved under
`logs/practice-<timestamp>-*`.

This is a workaround for the unresolved camera-rendering crashes on this Intel
Arc system. DX11 and DX12 both failed during live diagnostics; reduced gears,
a 48 km/h ceiling, lower resolution, and renderer-thread changes did not cure
those failures. Vulkan and NullRHI also failed startup in this installation.
The existing speed/steering limits remain vehicle-control safeguards, not a
claim that a particular speed prevents graphics crashes.

Map mode owns synchronous ticks at at most 20 steps per second, with fixed
0.05-second physics and 0.01-second substeps; simulated time cannot race ahead
of the control loop. Camera
profiles are available only for explicit diagnostics through
`run_practice.ps1 -CameraProfile parking` (four distinct rigid cameras) or
`-CameraProfile safe` (one front camera). The map profile is the default.
Do not combine a map session with another process expecting RGB images or
owning synchronous world ticks.

The neural launcher below still requires `nn_policy_colab.json`. That trained,
deployable policy is currently absent; map practice does not fabricate or train
one. See `CRASH_DIAGNOSIS.md` for evidence and validation limits.

## Lightweight one-command start

Device 1 runs CARLA, traffic, weather, maps, pothole scenarios, and the
four-camera parking cockpit. Device 2 will run the neural-network workload and
the overhead/map visualization. Device 2 setup files are
`device2_requirements.txt` and `setup_device2.ps1`.

From this folder in Command Prompt, start the complete lightweight runtime with:

```cmd
launch_carla_ui.cmd
```

This one command starts CARLA off-screen and starts the headless neural car
driving itself in it. Nothing visual is loaded: no local gesture/webcam engine,
no browser dashboard, and no camera cockpit window. It is just CARLA plus the
car.

The launcher uses a low-quality 320x180 off-screen CARLA viewport capped at 20
FPS, and no CARLA RGB camera sensors are created by this path. The older visual
cockpit remains available through `run_device1_ui.cmd` only when explicitly
needed for manual testing. No local gesture/webcam engine is included in this
workspace. A separately operated computer may later send only bounded final
intent-bias JSON over the existing optional UDP receiver; it must not send video
or direct vehicle controls.

Stop everything with:

```cmd
stop_stack.cmd
```

For manual four-camera driving, use `run_practice.cmd`. It owns a single
low-load CARLA server, waits for the world (not only port 2000) to become ready,
then opens the cockpit. It removes an unresponsive stale CARLA process before
starting and stops only the server it started when the cockpit closes.

## Supervision, logs, and the thermal guard

`launch_carla_ui.cmd` does not start CARLA or the neural driver itself. It
runs a preflight health check and then starts a single detached supervisor
through the persistent `AutonomousDrivingAgent_Supervisor` Windows task,
`stack_supervisor.py`, which owns them. No gesture/webcam engine is part of
this stack; `stack_supervisor.py` only ever manages CARLA and the car.

**Why.** On 2026-09-09 a component wedged, Windows killed it as a hung
application, and the rest of the stack went with it. Nothing was logged,
because the old launcher fired everything into detached Scheduled Tasks whose
output went nowhere, and nothing restarted them.

What the supervisor does:

- **Logs everything.** `logs/supervisor.log` plus `logs/carla.log` and
  `logs/neural.log`. Live state is `logs/stack_status.json`. A component log
  larger than `--max-log-mb` (default 50) is rolled to `.1`/`.2`/`.3` when
  that component is next started. Note this happens at start time only: a
  single uninterrupted run writes to one inherited handle and can exceed the
  cap, so a stack left up for weeks should be restarted or given a smaller
  cap. The neural driver is the volume driver at roughly 7 MB per hour.
- **Probes for liveness, not just a live PID.** CARLA must answer real RPC requests and advance its asynchronous world.
  An open TCP port alone does not pass the check. A process that is alive but no longer answering is recycled
  rather than left to Windows.
- **Starts in dependency order.** The neural driver waits for a real probe
  success from CARLA, not merely for it to have been spawned.
- **Restarts with exponential backoff** (5s doubling to 120s) and gives up after
  8 failed starts rather than thrashing a hot machine.
- **Kills process trees.** `CarlaUE4.exe` is a shim around
  `CarlaUE4-Win64-Shipping.exe`, and these venvs use a redirector `python.exe`
  that re-executes the base interpreter as a child. Terminating only the visible
  process orphans the real one, which is how a stale CARLA server ended up
  holding port 2000 while a second one started. It also sweeps any such orphans
  at startup.

### Thermal guard

This machine has an Intel Arc 140V integrated GPU and no discrete card, so
CARLA's renderer and the CPU share one thermal package. On 2026-09-09 it
logged a WHEA fatal hardware error and, an hour later, hibernated itself from
a critical thermal event.

Windows exposes no live temperature here - both `MSAcpi_ThermalZoneTemperature`
and the `ThermalZoneInformation` perf counters return nothing - so `health_guard.py`
reads the event log instead and refuses to launch inside a cooldown window: 30
minutes after a critical thermal event, 60 minutes after a fatal hardware error
or an unclean reboot. Check it by hand with:

```cmd
health_guard.py --window-hours 12 --json
```

Override the cooldown with `launch_carla_ui.cmd --force`. If the machine runs
hot, `launch_carla_ui.cmd --opengl` selects a renderer that is usually cooler
than `-dx12` on an Arc iGPU.

## Two-device architecture

The architecture diagram is in `device_architecture.md`. On Device 2, copy
this folder and the matching CARLA Python environment, then run
`setup_device2.ps1` after setting its `-CarlaRoot` path.

The CARLA display uses a six-zone parking cockpit: map at top-left, rear camera
across the top, instruments at top-right, tyre-facing mirrors down both sides,
and the windshield in the middle. Coloured parking guides and nearby-object
distances are drawn on the rear and mirror panels. A live local road minimap,
 digital/analogue speedometer, estimated-RPM tachometer, manual gear, visual
 P/R/N/D selector, clutch state, and parking-brake status are
overlaid on Device 1.

Scenario categories are recorded in `scenario_catalog.py`: urban, highway,
rural, intersection, additional maps, weather variants, and three pothole
modes (visual, physical, and avoidable-or-crossable).

Device 1 controls: `1` through `6` select the real forward gear; `,` and `.`
shift down/up; `R` selects reverse; `N` selects neutral; and `P` is a visual
selector backed by neutral plus the parking brake. Hold left `Shift` or left
`Ctrl` as the clutch while shifting above 1 km/h. `W`/Up is the accelerator,
`S`/Down is the brake, and `A`/`D` or Left/Right steers. `H` toggles
the handbrake, Space holds it, `Backspace` resets the car, and `C` cycles clear,
rain, heavy rain, fog, and snow/low-grip weather. The mirror
panels display nearest road-user distances and use exterior-style camera
positions that include the vehicle body where visible.

To keep all four feeds smooth while CARLA streams scenery on this laptop's
integrated GPU, the visible cockpit uses a progressive graphics throttle and
an enforced 48 km/h scene-streaming stability limit. Above 42 km/h it removes
throttle and progressively applies the brake. The HUD shows
`48 KM/H STABILITY LIMIT` while it is active. The independent stability limit
cannot be raised by the optional graphics-throttle command-line settings.

At 45 km/h the visible cockpit also enters `REDUCED MOTION` mode. It clears
moving clouds, rain, fog and dust and sets wind to zero so foliage is not being
animated for scenery that passes too quickly to matter. The chosen weather and
road wetness are retained and restored after speed falls below 38 km/h. The
45/38 km/h hysteresis prevents rapid switching and can be adjusted with
`--visual-austerity-start-kmh` and `--visual-austerity-resume-kmh`.

CARLA's stock Mustang maps manual gear `0` back to first gear internally, so
the cockpit implements `N` as a deterministic zero-torque neutral state and
keeps the driver-facing selector on `N`. Reverse and forward gears 1–6 are sent
as real CARLA manual gears. The HUD reads back the applied gear and warns only
when an unexpected forward/reverse mismatch occurs.

The Mustang's original four-speed physics are replaced for this cockpit with
six stability-matched bands: M1 `0–12`, M2 `9–20`, M3 `17–28`, M4 `25–36`,
M5 `33–42`, and M6 `39–48 km/h`. The physical ratios are `12.9275, 7.7565,
5.5404, 4.3092, 3.6936, 3.2319`, using a 4.27 final drive, 1.84 m tyre
circumference, 800 RPM idle, and 6000 RPM redline. Every gear reaches redline
near its upper band limit, with M6 matching the enforced 48 km/h ceiling.
Automatic route driving and manual HUD shift guidance use these exact speed
boundaries. The stock torque curve is preserved through 4500 RPM and extended
to 6000 RPM.

The speedometer uses natural-width digits (`0`, `8`, `42`, `48`) rather than
zero-padded text. The tachometer is a 0–7 x1000 RPM analogue dial with numbered
major ticks, a dedicated 6000 RPM redline arc, and a contrasting needle and hub.

The neural action protocol is now:
`[accelerator, brake, clutch, handbrake, wipers, steering_angle_degrees, gear]`.

The non-training infrastructure is now present:

- `safety_supervisor.py`: collision, lane, speed, red-light, stale-command,
  and sensor-timeout override layer;
- `episode_recorder.py`: replayable JSONL episode logging;
- `device_watchdog.py`: Device 1/Device 2 heartbeat and command timeout;
- `route_planner.py`: CARLA route-planning boundary;
- `evaluation_dashboard.py`: evaluation report generator for recorded episodes;
- `map_features.py`: road, lane, junction, route, and traffic-light features.

Generate an evaluation report after recording episodes with:

```powershell
python .\evaluation_dashboard.py .\episodes\*.jsonl --output evaluation_dashboard.html
```

It already contains the CARLA Python environment, CARLA 0.9.16 client package,
the bundled example/utilities dependencies, the built-in maps, and a custom
`spawn_car.py`. The installed dependency snapshot is
`requirements-carla-0.9.16.txt`.

## Current driving harness

Run CARLA first, then from the CARLA folder:

```powershell
.\carla_env\Scripts\python.exe .\spawn_car.py --window-width 1280 --window-height 720
```

Resize the window from the terminal:

```powershell
.\carla_env\Scripts\python.exe .\spawn_car.py --window-width 1280 --window-height 720
```

To let a neural network control this same visible car, use the GUI harness in
terminal-action mode:

```powershell
.\carla_env\Scripts\python.exe .\spawn_car.py --window-width 1280 --window-height 720 --agent-stdin
```

Pipe JSON actions into that process using the action format below. If no fresh
action arrives for 0.25 seconds, the car brakes for safety. Tune that deadline
with `--agent-timeout` when the controller runs at a slower known rate.

For an unattended cockpit smoke test, add `--max-runtime-seconds 10` and a
`--screenshot-path`; the process will save a complete frame and clean up its
vehicle and sensors before exiting.

Controls:

- Click the cockpit window first; a large warning appears when it lacks focus
- `1-6`: select the actual forward gear; `,`/`.` shifts down/up
- Hold left `Shift` or left `Ctrl`: clutch (required to shift while moving)
- `P/R/N`: visual park, reverse, neutral; forward gears light visual `D`
- `W`/Up: accelerator; `S`/Down: brake
- `A/D` or Left/Right: steer; steering remains active in reverse
- `Space`: handbrake while held; `H`: toggle handbrake
- `Backspace`: reset vehicle
- `Esc`: quit

Keyboard holds are tracked from key-down/key-up events instead of being sampled
once per render frame. A 35 ms tap latch (about two 60 FPS display frames)
preserves quick taps without the former 120 ms release delay; it can be tuned
with `--input-latch-ms`. The diagnostic parking profile uses four distinct rigid cameras, with no
camera teleporting or front-image duplication. The default map profile uses
zero RGB cameras and disables scene rendering.
The cockpit render loop is capped at 30 FPS. The windshield shows
`LIVE INPUT` while a driving key is held, and the terminal emits `[control]`
records containing the exact
throttle, brake, steering, handbrake, gear, focus, and received keys. Steering
direction remains physically consistent in forward and reverse. Keyboard
steering is progressively capped at 72% road-wheel command, and drive torque is
smoothly reduced during tight powered turns. The HUD labels this as `TURN
STABILITY`; steering remains under the driver's control. If the CARLA server
disappears, the cockpit uses a two-second runtime RPC timeout and closes instead
of remaining as an unresponsive window with frozen cameras. The visible cockpit
is limited to 48 km/h because repeated live runs at roughly 50–56 km/h caused
native UE4 crashes while streaming scenery on the Intel Arc iGPU. Throttle
narrows above 38 km/h, becomes zero at 42 km/h, and bounded braking rises to
65% at the 48 km/h ceiling. Steering is also progressively limited from 72% at
20 km/h to 22% at 48 km/h so a held keyboard key cannot request a sharp turn at
the renderer's highest safe streaming speed.

The display includes front, rear, left, and right camera views plus a low-cost
overhead map view. It is a camera-based situational panel, not yet a rendered
road-network map.

The visible cockpit launcher loads `Town04` by default. Its highway section is
available for low-speed route testing, but the multi-view cockpit now enforces
a 48 km/h stability ceiling on this machine.
Pass a different installed map through `spawn_car.py --map MAP_NAME` when a
city or parking scenario is needed.

Press `M` in the cockpit to open the full-town destination map. Click a visible
road and the selection snaps to CARLA's nearest driving waypoint. CARLA's
global planner supplies route geometry only; the deployable contract-v2 neural
policy supplies steering, accelerator, and brake while the independent safety
supervisor can stop for a red light, obstacle, lane departure, or excessive
speed. The deterministic six-speed manager remains outside the model. There is
no BasicAgent control fallback. Until `nn_policy_colab.json` exists, is marked
deployable, and matches policy contract 2, a click is rejected instead of using
an untrained or legacy policy. Press `M` again to inspect or replace the
destination. Any manual driving input cancels neural route mode immediately,
and `Esc` closes the map before it closes the cockpit.

A CARLA 0.9.16-compatible Tartu real-city map package downloads separately to
`C:\Users\medha\Documents\CARLA\downloads\tartu_demo_v0.9.16.tar.gz`.
Downloading does not install or load it; installation should happen only after
the archive finishes and its package contents have been inspected. Progress is
written to `C:\Users\medha\Documents\CARLA\downloads\tartu_download_status.txt`;
`complete_city_map_download.ps1` finalizes the background transfer when done.

## Explicit ML control interface

`C:\Users\medha\Documents\CARLA\CARLA_0.9.16\control_policy.py` defines the
action interface used by the driving harness:

`[accelerator, brake, clutch, handbrake, wipers, steering_angle_degrees, gear]`

Accelerator, brake, and clutch are `[0, 1]`; handbrake is boolean; steering is
clamped to `-70..+70` degrees; gear is `-1` reverse, `0` neutral, or `1..6`.
CARLA has no clutch field, so clutch disengagement scales wheel torque to zero.
Engine RPM is estimated from speed, gear ratio, final drive, and tyre size in
`manual_transmission.py`; it is explicitly labelled estimated telemetry. CARLA itself
receives the correctly normalized `steer` value. The module also includes an
interpretable lane-error-to-turn-angle baseline and an objective function.

The first objective uses progress and elapsed time, with strong collision and
lane-departure penalties. Mileage is initially a fuel proxy because CARLA does
not automatically model the exact engine/battery powertrain. A later vehicle
model should replace that proxy with measured energy consumption.

## Neural-network terminal control

The first runnable neural-network baseline is `neural_drive_agent.py`. Run
`run_neural_driver.cmd` from this Desktop folder, or use:

```powershell
cd "C:\Users\medha\Desktop\Autonomous driving agent"
& "C:\Users\medha\Documents\CARLA\CARLA_0.9.16\carla_env\Scripts\python.exe" .\neural_drive_agent.py --carla-root "C:\Users\medha\Documents\CARLA\CARLA_0.9.16" --tick-timeout 2.0
```

It loads the saved small pure-Python MLP and drives one hero vehicle. Training
is currently hard-disabled: startup never trains or overwrites the policy, and
`--bootstrap-train` exits with a clear error without changing weights. The
legacy pure-Python trainer has been removed; all training belongs in the
versioned Colab pipeline. The contract-v2 policy uses route-relative CARLA
map/vehicle state and traffic context; it is not a camera-trained end-to-end
network. The deployable artifact is `nn_policy_colab.json`. Legacy artifacts
without contract-v2 metadata are rejected so they cannot silently control the
car with incompatible inputs.

The saved model remains the primary controller. If it requests no useful
accelerator for two seconds while stopped on a clear, centered road, the live
runtime applies a bounded rule-based stall recovery capped at 0.35 accelerator.
A model brake request is always respected while moving. If the model
holds that brake for five seconds at a verified clear-road standstill, recovery
may release it; the environmental safety supervisor still has final authority.
Recovery is immediately disabled for a red light, nearby obstacle, excessive
lane/heading error, invalid telemetry, or after the vehicle reaches 85% of
target speed. Use `--disable-stall-recovery` for policy-only evaluation.
Runtime telemetry labels each tick as `policy` or `stall_recovery`; this
assistance is not training and never changes `nn_policy_colab.json`.

## Google Colab imitation training

The first trainable path uses CARLA's `BasicAgent` as a rule-based expert. With
CARLA already running, collect at least ten successful route-separated
demonstrations with:

```cmd
run_expert_collector.cmd
```

For human demonstrations instead, run `run_human_demo.cmd`. Training recordings
use Town05; Town04 remains excluded from training for the final unseen-map demo.
Press `M`, choose a road at least 150 m away, and follow the green route on the
live map. A completed collision-free route with at least 100 samples is moved
into `episodes\expert`; crashes, resets, and interrupted attempts remain in
`episodes\human_pending` and are not uploaded. Repeat until the cockpit reports
`12 HUMAN DEMOS COMPLETE`. Human recording uses the real manual gearbox: hold
Shift or Ctrl as the clutch and press comma/period to shift down/up, or hold the
clutch and press `1` through `6` for a direct gear. At a standstill, direct gear
selection does not require the clutch.

Each route is saved as its own file under `episodes\expert`. The records contain
the same eight route-conditioned observations used by the live MLP, the expert steering,
accelerator, and brake labels, telemetry, and scenario metadata. Collect data
across multiple maps, traffic loads, and weather presets before treating a
trained policy as an evaluation candidate.

Upload the episode files to `MyDrive/CARLA/episodes` and open
`colab_train_policy.ipynb` in Google Colab. The notebook splits complete
episodes—not individual frames—into train, validation, and test groups, trains
an `8 -> 24 -> 16 -> 3` PyTorch model, reports held-out errors, and exports a
JSON artifact compatible with `neural_drive_agent.py`. Legacy or
non-route-conditioned rows are rejected. When no real episodes
are present, it runs only a clearly labelled synthetic smoke test and exports
`nn_policy_smoke_test.json`, which must not be deployed.

For the map-click demo, download the real training output to exactly
`C:\Users\medha\Desktop\Autonomous driving agent\nn_policy_colab.json`. Then
start `run_device1_ui.cmd`, press `M`, and click a road. The global route planner
chooses only the waypoint sequence; the trained network produces every steering,
accelerator, and brake command. BasicAgent is not imported by the cockpit and
cannot take over the demo. A manual driving key cancels the route immediately.

Each telemetry record also includes non-visual checkpoint reinforcement. The
checks cover finite state, lane centering, heading alignment, suitable speed,
following distance, traffic-light compliance, smooth steering, non-conflicting
throttle/brake, collision safety, and lane safety. Passing checks receive
positive points and failures receive safety-weighted penalties; passing all
checks adds a completion bonus. This signal is currently logged for auditing
and is ready to be consumed by a future online/RL weight-update loop.

For a policy that sends decisions from another process, run:

```powershell
.\carla_env\Scripts\python.exe .\agent_drive.py
```

Send newline-delimited JSON actions through standard input:

```text
{"accelerator":0.35,"brake":0,"clutch":0,"hand_brake":false,"steering_angle_deg":-8,"gear":1}
```

The client prints one JSON telemetry record after every action. The model must
send actions repeatedly at a fixed rate; it should not send accelerator and
brake together. This client is intentionally GUI-independent and is the first
clean control boundary for training or inference.

## Additional maps

The supplied archive is not a standalone executable. Its paths are already
relative to the CARLA installation, so use the included safe dry-run command:

```powershell
.\install_additional_maps.ps1
```

To actually extract after checking the dry-run output, close CARLA and run:

```powershell
.\install_additional_maps.ps1 -Force
```

The archive contains additional Town11/Town12-family assets and supporting
content. Do not load a map until its archive has been extracted.

## CAT-cable connection

The direct CAT link must use a stable private address rather than an automatic
`169.254.x.x` fallback. Run PowerShell as Administrator on Device 1:

```powershell
.\configure_device1_link.ps1
```

Configure Device 2's wired adapter as `10.42.0.2/24`, then run the link test on
Device 2. Device 1 hosts CARLA at `10.42.0.1`:

```powershell
.\test_device1_link.ps1
```

Then Device 2 runs the neural client with `--host 10.42.0.1 --port 2000`.

Run `device2_specs.ps1` on Device 2 and bring its output back for hardware
matching. On Device 2, run `configure_device2_link.ps1` as Administrator, then
run `test_device1_link.ps1`. On Device 1, run `allow_carla_rpc.ps1` as
Administrator. `run_device2_neural_client.cmd` is the prepared remote-client
launcher; edit `CARLA_ROOT` if CARLA is installed elsewhere on Device 2.
Do not assign a gateway on the direct CAT link. The adapter is currently
negotiating at 100 Mbps; use a gigabit-capable USB adapter and CAT5e/CAT6 cable
if sensor streaming becomes bandwidth-limited.

## Roadmap toward one-car autonomous driving

1. Stabilize the simulator loop: fixed timestep, low sensor rates, one hero car,
   controlled NPC traffic, and repeatable spawn/destination scenarios.
2. Build the observation interface: front/side/rear cameras, depth or LiDAR,
   semantic segmentation, vehicle state, traffic-light state, and route/map
   features.
3. Start with a safe expert baseline using CARLA agents, then collect logged
   demonstrations and evaluate learned steering/throttle on held-out routes.
4. Add planning objectives for collision-free progress, time, comfort, and
   fuel/energy proxies. Do not optimize time or mileage before safety constraints.
5. Add gesture input as a probabilistic intent bias only; it must never override
   perception, traffic rules, or a safety controller.
