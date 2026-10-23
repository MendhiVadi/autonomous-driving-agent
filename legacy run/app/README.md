# Application code

The files directly in this folder are command entry points. Shared behavior
belongs to the packages below; scripts and tools add this app directory to
their own process's imports.

| Package | Owns |
| --- | --- |
| cockpit | Interactive session, command-line options, input, navigation and graphics helpers |
| vehicle | Commands, transmission and final safety arbitration |
| simulation | World lifecycle, observations, routes and road geometry |
| learning | Existing imitation policy, model contract, assistance and diagnostic scores |
| runtime | Paths, health, process lease, watchdog, archive validation, gesture input |
| telemetry | Episode recording, diagnostic reports and read-only activity page |

The remaining cockpit session is orchestration for the existing UI. Further
renderer/event-loop extraction should preserve its current behavior and be
validated with a live cockpit trial. New reinforcement-learning code does
not belong in these legacy packages.
