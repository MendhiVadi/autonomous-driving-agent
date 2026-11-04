# Project

Build a two-laptop CARLA system. Laptop 1 owns simulation, rendering, world ticks,
vehicle commands and final safety. Laptop 2 owns future reinforcement learning,
inference and navigation decisions. Training will start from random initialization.

## Applications

| Folder | Purpose |
| --- | --- |
| `laptop 1` | Full-graphics CARLA host and authenticated TLS gateway |
| `laptop 2` | Independent portable client, connection diagnostics and future trainer |
| `legacy run` | Preserved one-laptop manual and assisted imitation-learning system |

The legacy policy is preserved and does not initialize the new RL trainer.
The intended finished presentation retains Epic graphics, scenery, shadows and
wind-blown foliage. Each application owns independent source and output paths.

## Verified and pending

The layout check, localhost TLS rehearsal and extracted laptop 2 package tests
passed after the folder rename. These rehearsals use toy physics, not CARLA.
The first physical two-PC gateway test and model/training integration are pending.
The CARLA gateway adapter currently supports short empty-road engineering tests.
It is not ready for traffic or pedestrian training. Use Town02_Opt for connection
testing; Town13 gateway initialization remains unreliable.

Source authority: root `README.md`, laptop 1 `docs/PROTOCOL.md` and
`docs/CONNECT_SECOND_PC.md`, laptop 2 `docs/IMPLEMENTATION_PLAN.md`.

