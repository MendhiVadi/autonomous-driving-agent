# Decisions

- Folder names are `laptop 1`, `laptop 2`, and `legacy run`.
- Laptop 1 owns CARLA, rendering, physics, world ticks and final safety.
- Laptop 2 owns the future RL/model work and uses the existing TLS reset/step client.
- New RL begins from random initialization; the legacy imitation policy remains preserved.
- File transfer uses authenticated SMB on the direct Ethernet adapter. Live observations
  and actions use the existing gateway on TCP 8765.
- Town02_Opt is the first-connection baseline. Town13 gateway operation is experimental.
- One AI tool writes at a time. Independent applications do not import sibling source.
- Root `vault` is the laptop 1 knowledge source. Laptop 2 receives a dated ordinary-file
  snapshot and may add its own local notes. There is no automatic two-way Obsidian sync.
- 2026-10-06: preserve the legacy cockpit handoff as a portable snapshot; it
  does not change laptop 2's role or authorize model training. See
  [[Three-Camera-Neural-Driving-Handoff]].

