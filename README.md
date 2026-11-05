# Autonomous driving agent

A CARLA 0.9.16 project for one Windows laptop. Drive a car yourself with full
graphics, or pick a destination on a map and let a small neural network drive
there, on a small town or on the 10 x 10 km Town13.

## The three commands

| Command | What opens | Graphics |
| --- | --- | --- |
| **`run_car.cmd`** | One manual car in CARLA's own window. Town02_Opt, every scenery layer, wind-blown foliage, no neural network. | Epic quality, 1280 x 720, 30 FPS cap |
| **`run_neural.cmd`** | Town02_Opt with a destination map, the neural network and a three-camera cockpit (front view plus left and right mirrors) with instruments, a live map and a network activity web page. | Epic cameras rendered off screen, 960 x 540 cockpit, 15 FPS |
| **`run_large_map_neural.cmd`** | The same cockpit and network on Town13, streaming the tiles around the car. Experimental: long routes with sharp corners can stop the car. | Same, with lower camera rates |

Double-click a command or run it from a console. Run one at a time: each
launcher starts its own CARLA server, shuts it down afterwards, and refuses to
start while another CARLA window or cockpit is open. Press **Esc** to leave.

## First-time setup

1. **CARLA 0.9.16 for Windows.** Extract the package so that `CarlaUE4.exe` is
   in `%USERPROFILE%\Documents\CARLA\CARLA_0.9.16`. Any other location works if
   you set the `CARLA_ROOT` environment variable or edit `carla_root` in
   `config\runtime.json`.
2. **Python.** Install 64-bit Python 3.12 from python.org (tick *Add to PATH*).
   Any version with a client wheel in `<CARLA_ROOT>\PythonAPI\carla\dist` works.
3. **Python environment.** The first `run_*.cmd` offers to create it. It lives in
   `<CARLA_ROOT>\carla_env` and holds the CARLA client plus pygame, numpy,
   networkx and shapely. To create it yourself:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_environment.ps1
   ```

4. **Town13 only.** Download `AdditionalMaps_0.9.16.zip` from the CARLA 0.9.16
   release into the folder that contains your CARLA folder, close CARLA, then:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_additional_maps.ps1 -Force
   ```

   Without `-Force` the script only validates the archive.

5. **Neural network weights.** The launcher looks for `nn_policy_colab.json` in
   this folder, the network trained on real CARLA expert demonstrations. If it
   is absent it falls back to the bundled `nn_policy_bootstrap.json` and prints a
   warning. See [Which network is driving](#which-network-is-driving).

## Controls

**Manual car** (`run_car.cmd`): click the CARLA window first. **W/S** or
**Up/Down** accelerate and brake, **A/D** or **Left/Right** steer, **Space**
handbrake, **R** toggles reverse while stopped, **C** switches chase and bonnet
view, **Esc** exits. The car brakes whenever the window loses focus.

**Neural cockpit** (`run_neural.cmd`, `run_large_map_neural.cmd`): the
destination map opens first; click a road and the network drives there with
the route drawn in green. **M** reopens the map, **F8** reopens the network
activity page, **Backspace** resets the car to a fresh spawn, **Esc** closes
the map and then the cockpit. Any driving key (**W/A/S/D**, arrows, **Space**)
cancels the route and gives you manual control; **R/N/P** select reverse,
neutral and park. The stock automatic gearbox shifts itself. Losing focus
brakes the car.

If the car stops off its route the cockpit counts down three seconds, puts it
back on the route (up to three times per route) and the activity page shows
the same countdown. Collisions, obstacles and red lights are never recovered
automatically: press Backspace.

## Options

Every command passes extra options to `scripts\launch.ps1`:

| Option | Effect |
| --- | --- |
| `-Lightweight` | Neural mode without any 3D rendering: the map cockpit at 1280 x 720 and 20 FPS, DX11, the most stable mode on a weak GPU |
| `-Map Town05` | Another installed map (Town11/12/13 count as large maps) |
| `-MaxRuntimeSeconds 60` | Bounded session that exits by itself |
| `-RenderApi dx11` | Override the renderer (cameras default to DX12, camera-free modes to DX11) |
| `-NoNeuralVisual` | Do not open the activity web page |
| `-NoLaneAssist` | Raw network steering without the bounded lane correction |
| `-SpawnIndex 7` | Fixed spawn point instead of a random one |
| `-IgnoreHardwareCooldown` | Skip the thermal/hardware-fault cooldown check |
| `-StartupTimeoutSeconds 900` | How long to wait for CARLA to boot (default 420 s; the first start after an install is slowest) |

Example: `run_neural.cmd -Lightweight -MaxRuntimeSeconds 120`.

## Which network is driving

The network is an 8-24-16-3 multilayer perceptron. Its eight inputs are road
and vehicle state, not camera pixels: lane offset, heading error to a point
8 m ahead on the planned route, speed, target speed (30 km/h), distance to
the vehicle ahead, red-light flag, route curvature and a stopped flag. Its
three outputs are steering, accelerator and brake. Bounded lane assistance,
start assistance and an independent safety supervisor (collision, obstacle,
lane departure, red light, speed, stale commands) run after inference. The
activity page shows the real activations of every forward pass.

| File | Origin | Used when |
| --- | --- | --- |
| `nn_policy_colab.json` | Trained in Colab on CARLA BasicAgent demonstrations collected by this project ([docs/TRAINING.md](docs/TRAINING.md)) | Present in this folder |
| `nn_policy_bootstrap.json` | Bundled fallback distilled from a rule-based teacher on synthetic states by `tools\train_bootstrap_policy.py`; it drives but has never seen real CARLA data | `nn_policy_colab.json` is missing |

The launcher prints which file it loaded. Commit your trained
`nn_policy_colab.json` so a reinstalled machine keeps it.

## Training your own network

`docs/TRAINING.md` walks through the pipeline: record BasicAgent demonstrations
(`scripts\launch.ps1 -Mode expert`), optionally your own (`-Mode human-demo`),
bundle them, train in Google Colab with `colab_train_policy.ipynb` and copy
the exported `nn_policy_colab.json` here.

## Tests

```powershell
& "$env:USERPROFILE\Documents\CARLA\CARLA_0.9.16\carla_env\Scripts\python.exe" tools\verify.py
```

The suite needs no running simulator. Any Python 3.11+ with pygame, numpy and
nbformat can run it: when the real `carla` package is absent, a small stub in
`tests\stubs` stands in and the two tests that need the real API skip.

## Hardware notes

This project was developed on a laptop with an Intel Arc 140V integrated GPU:

- RGB cameras hang the CARLA server within seconds under DX11 there, while
  three Epic cameras ran for minutes under DX12, so camera modes default to
  DX12. Details and measurements: [docs/CRASH_DIAGNOSIS.md](docs/CRASH_DIAGNOSIS.md).
- Camera widths are rounded to multiples of 64 px; 240 px wide feeds arrived
  with sheared rows.
- The launcher refuses to start for a while after Windows logs a critical
  thermal or hardware fault (`app\runtime\health.py`).
- If the three-camera cockpit stutters, use `run_neural.cmd -Lightweight`.

## Layout

| Path | Purpose |
| --- | --- |
| `run_car.cmd`, `run_neural.cmd`, `run_large_map_neural.cmd` | The three entry points |
| `scripts/launch.ps1` | Owns the CARLA server, preflight checks and the chosen mode |
| `scripts/setup_environment.ps1`, `scripts/install_additional_maps.ps1` | One-time setup |
| `app/manual_drive.py` | Full-graphics manual car |
| `app/neural_cockpit.py`, `app/cockpit/` | Neural cockpit: session, HUD, input, navigation, recovery |
| `app/learning/` | Network, input contract, bounded assistance |
| `app/vehicle/` | Vehicle commands, transmission model, safety supervisor |
| `app/simulation/` | World lifecycle, observations, road geometry |
| `app/runtime/` | Paths, hardware health, watchdog, map archive validation |
| `app/telemetry/` | Episode recorder and the network activity page |
| `app/collect_expert_data.py`, `colab_train_policy.ipynb`, `tools/` | Training pipeline, bootstrap trainer, test runner, render probe |
| `config/runtime.json` | CARLA location and the ordered list of policy files |
| `tests/` | Offline regression tests |
| `docs/` | Training guide, crash evidence, network diagrams, project report draft |

Runtime output goes to `logs/` (server and cockpit logs, a cockpit screenshot
per run), `episodes/` and `exports/`; all three are ignored by Git.

## Known limits

This is assisted, state-input imitation learning on empty roads. It is not a
camera model and not validated road autonomy. Town13 neural driving loads and
runs but has stopped at sharp corners on long routes. The bootstrap policy is a
stand-in until a real model is trained. Real keyboard focus in the three-camera
cockpit was verified with scripted key replay, not yet by hand.
