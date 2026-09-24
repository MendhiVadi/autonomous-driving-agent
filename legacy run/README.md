# Legacy driving runtime

The one-computer application includes native manual driving, a map cockpit, imitation-policy inference, demonstration recording and a live network-activity page. Its source and configuration are independent of the two-computer applications.

## Installation

Install CARLA 0.9.16 and set `CARLA_ROOT`, or edit `config/runtime.json`. The launchers use a Python environment at `<CARLA_ROOT>/carla_env` with CARLA's matching API and the packages in `requirements/requirements-carla-0.9.16.txt`. Notebook and regression tools also use `nbformat` and OpenCV; the tested NumPy/OpenCV pairing is NumPy 1.26.4 and opencv-python 4.10.0.84.

CARLA binaries, environments, datasets and trained weights are not included. Neural mode requires a deployable, route-conditioned contract-v2 policy named `nn_policy_colab.json` in this folder. Manual mode does not require weights.

## Driving

Run commands from this folder:

| Command | Mode |
| --- | --- |
| `run_car.cmd` | Native CARLA viewport with full scenery and manual controls |
| `run_neural.cmd` | Lightweight destination map and supplied imitation policy |
| `run_practice.cmd` | Map cockpit without opening destination selection immediately |
| `run_training.cmd` | Collect expert demonstrations |
| `run/run_human_demo.cmd` | Record manual demonstrations |
| `verify.cmd` | Offline regression tests |

For native manual driving, click CARLA and use WASD/arrows, Space for the handbrake, R to reverse while stopped, C to change view, and Esc to exit. The car brakes on focus loss.

In neural mode, select a road on the map. M reopens destination selection, driving keys take over, and F8 opens network activity. `run_neural.cmd -NoNeuralVisual` skips the activity page. Close one session before starting another. See [driving modes](docs/TWO_MODES.md).

## Source layout

`app/` contains the cockpit, vehicle, simulation, runtime, learning and telemetry packages. `scripts/` owns startup and cleanup; `tools/` contains dataset and notebook utilities; `tests/` holds regressions. Configuration is local to this application. Runtime output is written to `logs/`, `episodes/` and `exports/`.

The policy uses eight road and vehicle features. Lane/start assistance and a separate safety supervisor follow inference. This is assisted imitation learning, not a validated camera-based autonomous driver. The native viewport has passed bounded manual checks; the older RGB camera cockpit remains experimental. See [rendering notes](docs/CRASH_DIAGNOSIS.md) and [architecture](docs/device_architecture.md).
