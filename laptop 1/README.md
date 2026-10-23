# Primary laptop

This is the simulation host for the new two-laptop system. It owns CARLA,
graphics, physics, vehicle actuation and local safety.

## Available now

`run_manual.cmd` starts this folder's independent native-viewport manual mode:
Epic graphics, all map layers, 1280×720, 30 FPS cap, wind intensity 65.
Click CARLA; WASD/arrows drive, Space handbrake, R reverses while stopped,
C changes view, Esc exits. Loss of focus applies the brake.

`run_manual.cmd -Check` checks dependencies without launching CARLA.
`run_manual.cmd -MaxRuntimeSeconds 30` bounds a manual session.

`config/runtime.json` owns the installation and default map.
An explicit `-CarlaRoot` or `CARLA_ROOT` overrides the installation location.
The source of the graphics settings is `src/sim_host/profiles.py`.

## Layout

- `src/sim_host/`: manual driver, presentation profile, world ownership,
  watchdog and hardware-health guard.
- `scripts/`: owned-process startup and cleanup.
- `config/`: local installation settings.
- `logs/`: generated evidence, created on launch.
- `tests/`: offline host behavior checks.

The experimental local/TLS gateway now supplies reset/step, bounded controls,
deadline/session/replay checks, and disconnect braking. It is **not** a complete
traffic safety supervisor or a training-ready environment. Manual mode does
not run a neural policy. The final trained-policy mode must retain full
graphics, including animated foliage; it must not inherit the legacy
camera-cockpit speed-triggered reduced-motion setting.

Copied support modules belong to this application. Imports and paths stay
inside this folder. Third-party CARLA binaries are external dependencies.
The host's isolated API environment is preferred; the older external Python
environment remains a compatibility fallback, never a source of project code.

Run `python -B tests/run_tests.py` for offline checks (standard library only).
The independent launcher passed a bounded live startup on September 23, 2026:
native full-graphics mode, wind 65, approximately 25.5 FPS while stationary,
followed by shutdown. This does not establish driving performance or remote
RL operation. See the dated logs in this folder.

## No-training connection preparation

`python -I -B gateway.py --port 8765` starts the lightweight toy backend.
Set `SIM_GATEWAY_TOKEN` to a newly generated random secret of at least 32 ASCII
characters in both process environments; it is never written to a config/log.
The root maintenance checker automates this for a one-command local rehearsal.

`run_gateway.cmd -SingleSession -MaxRuntimeSeconds 150` starts managed CARLA
with the same full-graphics profile. It requires the token before launch.
The independent client can then reset and step. Default diagnostics hold the
brake; motion requires the client's explicit `--allow-motion` flag. With
`-SingleSession`, closing the first authenticated session also shuts down the
managed simulator. The runtime cap is checked between bounded operations;
a map load can take up to 90 seconds, and physics calls up to 5 seconds.

Plaintext is supported only on `127.0.0.1`. Private IPv4 operation requires TLS,
the paired certificate/token and an explicitly allowed peer. No firewall rule
or permanent listening service has been added. See the connection-day checklist.
The CARLA adapter supports short seeded same-lane routes on an otherwise empty
map. Red-light and obstacle fixtures exist in toy physics, not as validated
CARLA traffic scenarios. Collision callbacks, traffic-light trigger coverage,
dynamic hazards and reward calibration still need dedicated validation before
training. Reset controls spawn/route selection; it does not promise bitwise
determinism or reset every global CARLA traffic-light clock.

See [protocol](docs/PROTOCOL.md), [preparation scope](docs/PRE_CONNECTION_PLAN.md),
and [map inventory](docs/MAPS.md). New modules are split into transport (`wire`),
session handling (`gateway`), episode semantics (`environment`), toy backend
(`rehearsal`) and optional simulator adapter (`carla_backend`).
See [dated validation](docs/VALIDATION.md) for passing checks and remaining limits.

## Two-PC launch

See [connection-day checklist](docs/CONNECT_SECOND_PC.md). `prepare_pairing.py`
creates protected, Git-ignored credentials once, with no overwrite/rotation.
`run_network.cmd PRIMARY_IP SECONDARY_IP` starts the encrypted gateway using
the small default map. The `allow_peer.ps1` script is explicit, supports
`-WhatIf`, and adds only the selected peer/adapter/port/private profile.

This host's launcher prefers its own `.venv` when present. It was created by
`scripts/setup_host_runtime.ps1` using the local official Python 3.12 wheel;
no training libraries were installed. The external legacy environment is
unchanged. CARLA map-transfer caches now belong to this host under `cache`.
