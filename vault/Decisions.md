# Decisions

- Folder names are `laptop 1`, `laptop 2`, and `legacy run`.
- Laptop 1 owns CARLA, rendering, physics, world ticks and final safety.
- Laptop 2 owns the future RL/model work and uses the existing TLS reset/step client.
- New RL begins from random initialization; the legacy imitation policy remains preserved.
- File transfer uses authenticated SMB on the direct Ethernet adapter. Live observations
  and actions use the existing gateway on TCP 8765.
- Town02_Opt is the first-connection baseline. Town13 gateway operation is experimental.
- The rendered legacy neural launcher retains the existing policy and safeguards.
  Full scenery uses a 20 FPS cap; the large Town13 map continues to stream tiles
  around the car instead of loading every tile at once.
- One AI tool writes at a time. Independent applications do not import sibling source.
- 2026-10-01: match the supplied neural visual references with real activations,
  white connections and steering/pedal diamonds. Retain the actual eight inputs
  and three outputs, distinguish raw/applied controls, and show replay or loss of
  connection explicitly. Freeze affects the browser display only.
- 2026-10-01: use a separate legacy Town13 neural launcher rather than coupling
  the independent laptop 1 app to legacy files. Preserve full map layers, Epic
  rendering, wind and safety checks; stream nearby CARLA tiles and sample the
  display/route graph more coarsely to fit the 10 km map.
- 2026-10-06: verify the legacy front/left/right graphics cockpit with the
  existing model and active safety checks before calling it reliable. See
  [[Three-Camera-Neural-Driving-Handoff]].
- 2026-10-06: camera profiles default to DX12. Every DX11 camera trial (13 variants incl.
  one camera, small main view, synchronous ticks, Low quality) lost its stream and RPC;
  DX12 ran three Epic offscreen cameras for 120 s with no RPC failure. An explicit
  `-RenderApi` still wins; the native map-profile window keeps DX11.
- 2026-10-06: the camera cockpit owns synchronous 15 Hz ticks (simulation 0.75x real time)
  instead of a free-running server (70-90 frames/s, ~66% vs ~44% GPU 3D load).
- 2026-10-06: camera widths are rounded to multiples of 64 px. 240 px feeds arrive sheared
  from the GPU read-back; this is not fixable by copying frames differently.
- 2026-10-06: the route reference point is 8 m ahead on every map (4 waypoints on Town02's
  2 m route graph, 1 on Town13's 8 m graph), matching what the policy was trained on.
- 2026-10-06: manual-control checks that need real keyboard focus are done by hand. The
  user declined computer-use access to the cockpit window, so no OS-level input is injected;
  `--scripted-keys` replays keys inside the cockpit and says it does not test focus.
- 2026-10-06: Town13 neural driving stays experimental; no thermal or safety limit was changed.
- 2026-10-06: a stationary neural-route car that is off its route is re-seated on the route after
  a 3 s countdown (max 3 times per route, within 40 m, never after a collision, obstacle or red
  light). The countdown is published to the HUD and the activity page so the wait is visible.
- Root `vault` is the laptop 1 knowledge source. Laptop 2 receives a dated ordinary-file
  snapshot and may add its own local notes. There is no automatic two-way Obsidian sync.

