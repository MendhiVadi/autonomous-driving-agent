# Simulation host

The primary application owns CARLA, rendering, physics, vehicle controls and local safety checks. It offers native manual driving and an authenticated reset/step gateway for the remote client.

## Setup

Install CARLA 0.9.16 for Windows and Python 3.12. Set `CARLA_ROOT` or edit `config/runtime.json`, then run these commands from this folder:

```powershell
powershell.exe -NoProfile -File scripts/setup_host_runtime.ps1
.\run_manual.cmd -Check
.\run_manual.cmd
```

The setup script creates `.venv` from the official API wheel bundled with CARLA. The environment and simulator are not included in this repository.

## Manual driving

Click the CARLA window. WASD/arrows drive, Space applies the handbrake, R reverses while stopped, C changes view, and Esc exits. Losing focus applies the brake.

Defaults are Epic graphics, all map layers, 1280 x 720, wind intensity 65 and a 30 FPS cap. `src/sim_host/profiles.py` defines the presentation settings. Use `run_manual.cmd -MaxRuntimeSeconds 30` for a bounded session. Town02_Opt is the default; see [map status](docs/MAPS.md) before trying Town13.

## Gateway

For an unencrypted localhost rehearsal, set a random `SIM_GATEWAY_TOKEN` of at least 32 ASCII characters in both processes and run `python -I -B gateway.py --port 8765`. The root `check_local_link.py` automates this test.

`run_gateway.cmd -SingleSession -MaxRuntimeSeconds 150` starts the managed CARLA backend. The token must be set before launch. The client can reset an episode and step bounded controls. Diagnostics keep the brake applied unless `--allow-motion` is supplied. Single-session mode shuts down after the first authenticated session closes.

Private-network operation requires TLS, paired credentials and an exact peer address. Create these with the root pairing instructions, then follow the [two-PC setup guide](docs/CONNECT_SECOND_PC.md). Network settings and firewall rules are changed only through the explicit setup scripts.

## Development

Source is under `src/sim_host`, launch scripts under `scripts`, and offline checks under `tests`. Run `python -I -B tests/run_tests.py`. Runtime logs and map caches are created locally.

The CARLA adapter supports short seeded same-lane routes on an empty map. Toy fixtures cover red lights and obstacles; CARLA traffic perception, collision timing and reward calibration need further work. The adapter is not ready for RL training. See the [protocol](docs/PROTOCOL.md), [development status](docs/PRE_CONNECTION_PLAN.md) and [validation notes](docs/VALIDATION.md).
