# Autonomous driving agent

Three independent application folders:

| Folder | Responsibility | Current status |
| --- | --- | --- |
| [laptop 1](laptop%201/README.md) | CARLA, graphics, physics, vehicle ownership and final safety | Full-graphics manual host and authenticated TLS reset/step gateway |
| [laptop 2](laptop%202/README.md) | Reinforcement learning from scratch, inference and navigation decisions | Portable paired client and no-training diagnostics; trainer pending |
| [legacy run](legacy%20run/README.md) | Complete current one-laptop system | Existing manual and assisted-neural modes, datasets, weights and tests |

## Run

For the existing neural system, open `legacy run` and run `run_neural.cmd`.
Its full-graphics manual mode is `run_car.cmd`.
For the same existing model with rendered scenery and its local activity page,
use `legacy run/run_graphics_neural.cmd`: a three-camera (front, left, right) Epic cockpit
rendered offscreen with DX12 (DX11 hangs CARLA on RGB cameras on this PC). Its Town02_Opt
manual and neural-route checks passed in bounded runs on 2026-10-06; real keyboard
focus by hand is still to be confirmed.

For the new simulation host's independent graphics/manual check, open
`laptop 1` and run `run_manual.cmd`. Use
`run_manual.cmd -Check` to validate paths/imports without starting CARLA.

Run `python -I -B check_local_link.py` for a two-process localhost rehearsal.
It uses toy physics and fixed controls: no CARLA launch, model, or training.
Use `legacy run/run_large_map_neural.cmd` for Town13 with the existing model,
full graphics and the neural activity website. Use `laptop 1/run_large_map.cmd`
for the separate manual map-only mode. In three bounded 2026-10-06 trials the neural
launcher loaded Town13 in about two minutes, ran its three cameras for 120-150 s
(cockpit 9-13 FPS) and shut down cleanly; the network drove a straight 120 m route to
its destination but stopped at the first sharp corner of a 200 m route (twice), so
Town13 neural driving stays experimental. Use the default
Town02_Opt for the first two-PC connection;
see the [map status](laptop%201/docs/MAPS.md) for the exact boundary.

The RL policy/trainer is not implemented. Encrypted LAN software is prepared;
physical two-PC routing/firewall/latency checks remain pending. The completed RL
system must drive with full scenery, Epic-quality graphics, shadows and
wind-blown foliage on the laptop 1. The existing trained imitation
policy is preserved inside legacy and will not initialize RL training.

## Independence

Each application owns its source, configuration, models and output paths.
Required helpers were copied as ordinary independent files. There are no
symlinks, shared source folders, sibling imports or fallback searches across
these three applications. The two new applications now exchange versioned
network messages locally or over a paired encrypted private-IP connection.
Non-loopback operation requires TLS and an explicit allowed peer. No firewall
rules or adapter settings are changed automatically.

CARLA's third-party installation and Python environment stay outside the
repository for legacy. The primary host now also has an isolated Python 3.12
environment using the official API wheel bundled with CARLA 0.9.16. Neither
application's code is loaded from the other. One CARLA
session runs at a time, enforced by the existing Windows session mutex.

## Project knowledge in Obsidian

Open `vault` as a folder vault in Obsidian and start with
[the knowledge index](vault/00-Index.md). AI agents read this index and maintain
the relevant notes alongside meaningful changes. Laptop 2 has a portable vault
snapshot included in its client package. The Ethernet transfer share also holds
`obsidian-vault.zip` for a standalone copy. These are explicit snapshots, not
automatic two-way synchronization. Preserve local notes when exchanging updates.

## Maintenance checks

Run `python -B verify_layout.py` with Python 3.11+ to check source isolation,
local documentation links, and Python syntax without launching a simulator.
Run `verify.cmd` inside `legacy run` for the retained system's regressions.
Each new folder also contains its own test runner or environment check.
The root link checker is maintenance orchestration only; neither application
depends on it when deployed separately.

See the [connection-day checklist](laptop%201/docs/CONNECT_SECOND_PC.md).
`python -I -B check_local_link.py --tls` tests the paired encrypted connection
without CARLA or training. The latest ZIP in `handoff` is for transfer to the
other PC; it contains a private client token and must not be uploaded publicly.

The previously approved four files remain deleted. This reorganization moved
the remaining one-laptop files without discarding them. Historical backups
and generated evidence are retained inside `legacy run`; do not treat them
as active source. See [maintenance notes](legacy%20run/docs/MAINTENANCE.md).
