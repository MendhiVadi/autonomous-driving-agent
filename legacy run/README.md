# Legacy run — current one-laptop system

This folder is self-contained application code for the retained one-laptop setup.
Its models, datasets, logs, commands, and tests are local to this folder. It has
no runtime dependency on either new laptop folder. All commands below are run
from **this folder**, not the repository root.

## Start here

Choose one of these two commands from this folder:

| Command | What opens |
| --- | --- |
| **`run_car.cmd`** | One manual car in CARLA's native 3D window, full scenery, shadows and wind-blown foliage; no neural model or extra camera cockpit |
| **`run_neural.cmd`** | Lightweight Town02_Opt destination map, existing trained network and live activity page; no 3D rendering or RGB cameras |
| **`run_graphics_neural.cmd`** | Epic three-camera cockpit (front plus left/right mirror feeds from an offscreen DX12 CARLA server), existing trained network, destination map and live activity page |
| **`run_large_map_neural.cmd`** | The same three-camera cockpit on Town13, streaming nearby tiles around the car; experimental |

In full graphics: click CARLA, use **WASD/arrows**, **Space** for handbrake,
**R** for reverse while stopped, **C** for chase/bonnet view, **Esc** to exit.
It brakes when the window loses focus. The default is Epic quality, 1280x720,
wind 65 and a 30 FPS cap.

In neural mode: click a road on the opening map. **M** reopens the map;
driving keys take over. **Esc** closes the map, then the cockpit.
**F8** reopens the network page; `run_neural.cmd -NoNeuralVisual` omits it.
The network page shows the real 8 → 24 → 16 → 3 activations and a steering/pedal
timeline. Switch between **Applied controls** and **Raw predictions**, or use
**Freeze view** to inspect values without pausing the car. Hover/tap a neuron
or focus the graph and use arrow keys to inspect its connections and value.
The existing cockpit and manual gears remain available.
The graphics neural launchers open a three-camera cockpit with the same model,
route selection and safeguards: a front view and left/right mirror views from an
offscreen Epic CARLA server, instruments, a live map and a status panel. There is
no separate CARLA window. Click the cockpit to drive with **W/S/A/D** or the
arrows (**Space** handbrake, **R** reverse, **N/P** neutral/park; the stock
automatic gearbox shifts itself), or press **M**, click a road and let the
network drive. Any driving key takes over from the network; losing focus brakes
the car. The cockpit ticks CARLA itself at 15 Hz, so simulated time runs at 0.75x
real time.

RGB cameras hang CARLA's server within seconds under DX11 on this Intel Arc
machine, so the camera launchers default to **DX12** (an explicit `-RenderApi`
wins). Camera widths are rounded to multiples of 64 px: 240 px wide feeds arrive
with sheared rows. Evidence and trials are in
[docs/CRASH_DIAGNOSIS.md](docs/CRASH_DIAGNOSIS.md).

If the car stops off its route the cockpit counts down 3 s ("OFF ROUTE - RE-ALIGNING IN 3 S"),
puts it back on the route (up to 3 times per route), and the activity page shows the same
countdown as a yellow line. Collisions, obstacles and red lights are never auto-recovered;
press **Backspace** to reset after those, or when the car is too far from the route.

Verified on 2026-10-06 (Town02_Opt, launcher-started, bounded): a 75 s run held
the cockpit at 15 FPS with front ~14.7 and side ~6 camera updates/s, no stall,
and exited cleanly; a scripted key replay (not real keyboard input) showed W/UP
throttle, S/DOWN brake, A/D and arrow steering that turned the car, and Space
handbrake. On a 276 m route the neural policy reached waypoint 131 of 140 in a
100 s run (the safety supervisor stopped it once at a red light), and with the
car deliberately rotated 180 degrees it was realigned to the road first, then
drove to the destination (waypoint 137 of 140) and stopped. The activity page's
sample counter climbed from 37 to 210 during a run. Not yet verified: real
keyboard focus by hand.
For Town13, use `run_large_map_neural.cmd`. Its whole-town map is sampled more
lightly for display and route lookup, while CARLA streams nearby scene tiles as
you drive. Three bounded 2026-10-06 runs loaded Town13 in about two minutes, warmed
tiles, ran the three cameras for 120-150 s (cockpit 9-13 FPS, front 6-9, sides 2-3
updates/s, dropping a little over successive runs) and shut down cleanly. On a
straight 120 m route the network drove to the destination with no safety
intervention; on a 200 m route it stopped twice at the first sharp corner, about
80 m along (collision, then lane departure; the safety supervisor held the
brakes). Treat Town13 neural driving as experimental.
`run_practice.cmd` remains a compatible entry point without the opening map.

Close one session before starting the other. Both new launchers reject an
already running CARLA instance so graphics settings cannot leak between modes.
See [controls, design and verification](docs/TWO_MODES.md).

This is assisted state-input imitation learning. The network uses eight
road/vehicle values; bounded lane/start assistance and an independent safety
supervisor follow inference. It is not a camera model or validated road autonomy.
The native viewport passed a bounded full-scenery driving test on this Intel Arc
machine. The earlier RGB sensor rendering fault is specific to DX11: three Epic
cameras ran stably under DX12 for minutes in the 2026-10-06 trials.

## Project layout

| Folder | Purpose |
| --- | --- |
| `run_car.cmd` | Full-graphics manual driving, one native viewport |
| `run_neural.cmd` | Lightweight neural driving, opening destination map |
| `app/cockpit/` | Session, input, options, map navigation, camera stability helpers |
| `app/vehicle/` | Vehicle command conversion, transmission, safety |
| `app/simulation/` | World settings, road geometry, observations, routes |
| `app/runtime/` | Paths, process ownership, watchdog, hardware health |
| `app/learning/` | Existing imitation-learning model, contract, assistance |
| `app/telemetry/` | Recordings, diagnostic dashboard, network activity page |
| `config/runtime.json` | CARLA location and explicitly allowed legacy model paths |
| `tests/` | Automated regression tests; no running simulator required |
| `tools/` | Dataset packaging, notebook generation, training and bounded live checks |
| `scripts/` | PowerShell launch, stop, installation and device setup |
| `run/` | Secondary launchers; `_practice.cmd` remains available |
| `requirements/` | Dependency snapshots for each workflow |
| `docs/` | Architecture, crash evidence and historical documentation |
| `docs/images/` | Network diagrams |
| `artifacts/screenshots/` | Previous cockpit screenshots |
| `episodes/`, `exports/` | Demonstrations, trained artifacts and reports |
| `logs/` | Runtime evidence; older root logs are in `logs/archive/` |
| `backups/`, `Claude outputs/`, `colab_artifacts/` | Preserved earlier work; not runtime source |

Application code lives in **`app/`**. Use the commands here; the historical
adapters in the CARLA installation still point to the former workspace layout
and are retired entry points. CARLA binaries remain in
`C:\Users\medha\Documents\CARLA\CARLA_0.9.16`.
Set `CARLA_ROOT` for a different installation; pass `-CarlaRoot` when invoking
`scripts/run_practice.ps1` directly. Commands resolve files from the project.

## Commands

| Command | Behavior |
| --- | --- |
| `run_practice.cmd` | Everyday map cockpit and neural activity page |
| `run_training.cmd` | Collect expert demonstrations; does not train weights |
| `run\run_human_demo.cmd` | Record manual demonstrations |
| `verify.cmd` | Run offline regression checks |
| `run\check_input_environment.cmd` | Bounded live simulator/input check |
| `run\launch_carla_ui.cmd` | Separate headless supervised mode; requires `nn_policy_colab.json` |
| `stop_stack.cmd` | Request cleanup from this project's headless supervisor |

Other launchers are in `run/`; device/network setup scripts are in `scripts/`. Camera
and presentation modes are experimental. Close one session before opening another.
An unresponsive unowned simulator is reported for manual closure, never killed
automatically by a new launcher. Close practice with Esc; `stop_stack.cmd`
addresses the separate supervised mode.

Run `verify.cmd` with both driving sessions closed: the ownership tests
deliberately acquire the same single-session lock as the launchers.

Startup checks the owned simulator process directly and tolerates a brief
handover to its worker process. If it exits before the world is ready, the
launcher prints its native exit code and saves a dated `startup-failure.txt`
report under `logs/`. A September 14 startup failure was not reproducible on
retry; the strengthened checks passed 153 regressions and a 25-second live
launch with the neural webpage and clean shutdown.

The Colab notebook remains `colab_train_policy.ipynb`. Its generator is
`tools/build_colab_notebook.py`. Dataset files and weights were preserved.
The legacy `nn_policy.json` is retained for rollback and is not deployable.

## Finish R1 checkpoint

`FINISH_R1.json` records the full backup scope and verification count.
The SHA-256 manifest, copied workspace, complete CARLA folder, and milestone
record are in the backup folder listed in [docs/REORGANIZATION.md](docs/REORGANIZATION.md).
Git tag **`Finish-R1`** marks the original project state. That tag is a source
checkpoint; use the full backup to restore the original CARLA-side custom files too.

See [docs/REORGANIZATION.md](docs/REORGANIZATION.md) for fixes and validation.
The two obsolete R1 documents and the experimental direct Device 2 launcher/setup
script were removed with approval. Their historical versions remain in Git.
