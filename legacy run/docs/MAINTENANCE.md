# Maintenance

The legacy application groups source into cockpit, vehicle, simulation, runtime, learning and telemetry packages. Each package remains local to this application.

Run `verify.cmd` with CARLA sessions closed so ownership tests can acquire the session mutex. The root layout audit checks imports, source isolation, Python syntax and documentation links.

Model loading validates dimensions, contract metadata and finite values. The activity endpoint caches unchanged weights, road rendering uses sampled geometry and a spatial index, and angle normalization runs in constant time. Watchdogs cover missing commands and retain ownership of callbacks during shutdown.

The legacy runtime remains an assisted imitation-learning baseline. The separate host/client applications provide the experimental two-PC gateway; their trainer is not yet implemented.
