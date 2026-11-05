# Application code

`manual_drive.py` (full-graphics manual car), `neural_cockpit.py` (neural
cockpit entry point) and `collect_expert_data.py` (training-data recorder)
are the processes `scripts/launch.ps1` starts. Shared behaviour lives in the
packages below; scripts and tools add this directory to their own imports.

| Package | Owns |
| --- | --- |
| cockpit | Interactive session, command-line options, keyboard input, map navigation, HUD, route recovery, camera helpers |
| vehicle | Vehicle commands, transmission model and the final safety supervisor |
| simulation | World lifecycle, large-map loading, observations, road geometry, RPC liveness probe |
| learning | Network, input contract and bounded assistance |
| runtime | Paths, hardware health, command watchdog, map archive validation |
| telemetry | Episode recording and the read-only network activity page |

`cockpit/session.py` is still a large orchestration module; split it only with
a live cockpit trial on the real machine to confirm behaviour is unchanged.
