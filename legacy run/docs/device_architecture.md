# One-laptop architecture

This document describes the retained system inside this application's folder.

CARLA state flows through `simulation.observations` into `learning.model`.
The saved contract-v2 imitation policy produces controls; bounded assistance
in `learning.assistance` precedes final arbitration in `vehicle.safety`.
The local command watchdog applies braking if control publication stalls.

`app/cockpit/session.py` owns the interactive map cockpit.
`app/spawn_car.py` is its stable command entry point.
`app/scenic_drive.py` owns the full-graphics manual viewport.

Map mode uses fixed 0.05-second physics ticks and no RGB cameras. The saved
model does not train during a drive; manual input cancels neural navigation.
The activity page in `app/telemetry/` displays actual forward-pass values.

All imports, model selection and outputs stay within this application.
Remote control is handled by the separate host and client applications.
