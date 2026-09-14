# Autonomous driving agent

## Start here

Run **`run_practice.cmd`** for the current lightweight driving system.
It starts CARLA on Town02_Opt without RGB cameras, opens the map cockpit,
loads the saved preliminary network and opens its live activity page.
Press **M**, choose a road destination, and use a driving key to take over.
Press **Esc** to close the destination map, then the cockpit.
Manual gears **M1–M6** and the existing cockpit layout remain supported.

This is assisted state-input imitation learning. The network uses eight
road/vehicle values; bounded lane/start assistance and an independent safety
supervisor follow inference. It is not a camera model or validated road autonomy.
The Intel Arc 3D-rendering fault remains unresolved; map mode is the default.

## Project layout

| Folder | Purpose |
| --- | --- |
| `app/` | Driving, cockpit, controls, safety, process supervision and local web panel |
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

All custom Python driving code now lives in **`app/`**. The four custom
Python files in the CARLA installation forward to that source for compatibility.
Do not edit those adapters. CARLA binaries remain in
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
The previous README is preserved as [historical notes](docs/archive/README-Finish-R1.md);
its old paths, startup advice and dated results are not current instructions.
