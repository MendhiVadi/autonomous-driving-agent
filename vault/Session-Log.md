# Session log

## 2026-10-06

- Added [[Three-Camera-Neural-Driving-Handoff]] to record the cockpit changes,
  incomplete graphics trials and outstanding verification.

- Verified and hardened the legacy three-camera cockpit on Town02_Opt (bounded,
  launcher-started runs; evidence in `legacy run/logs/render-probes-20261006/`,
  `legacy run/logs/practice-20261006-*`, `tools/render_probe.py`):
  - **Stall:** offscreen rendering did not avoid it. Under DX11 every camera trial
    lost its stream and all RPC within 1-10 s (cockpit setup, one camera, small main
    view, synchronous ticks, Low quality, variable timestep, no post-processing).
    DX12 ran three Epic cameras for 120 s with 0 RPC failures, so camera profiles now
    default to DX12.
  - **Corrupted side feeds:** 240 px wide buffers arrive with the right size but
    sheared rows (192/256/320/640 px are clean). Camera widths now round to multiples
    of 64 (sides 256x144). The earlier frame-copy change was not the cause.
  - **Pacing:** the free-running async server did 70-90 frames/s at ~66% GPU 3D load;
    the cockpit now ticks synchronously at 15 Hz (~44%). Launcher run, 75 s: cockpit
    15 FPS, front ~14.7 and sides ~6 updates/s, exit 0, no CARLA process left.
  - **UI:** HUD moved to `app/cockpit/hud.py`; fixed clipped labels, gauge/gear
    overlap, the centre-screen "click CARLA view" banner (no CARLA window exists
    offscreen), parking-guide clutter and the dead rear panel; stale feeds are labelled.
    Gear display and shift hints follow the stock automatic gearbox, and keyboard
    driving there no longer pins gear 1.
  - **Manual controls:** the user declined computer-use access to the cockpit window and
    a script cannot take the foreground, so real keyboard focus is NOT verified. An
    in-process replay (`--scripted-keys`) showed W/UP throttle 0.65 (0 to 17.7 km/h, gear
    1 to 2), S/DOWN brake 1.0, A/D and arrows steering that turned the car (yaw 90 to
    108), Space handbrake; an unfocused window brakes (throttle 0, brake 1).
  - **Neural:** route alignment had never worked: it required speed < 1 km/h on a car
    still settling from spawn (4-7 km/h) and then crashed on the non-existent
    `vehicle.set_velocity`. Both fixed (settle wait, `set_target_velocity`) and a test now
    checks every `vehicle.*`/`world.*` call against the real API. None of 3,275 Town02_Opt
    routes (101 spawns) needed alignment; with a 180 degree spawn rotation it logged
    "aligned ... 180.0 degrees" and the car drove to waypoint 137/140 and stopped. Without
    rotation: waypoint 131/140 in 100 s with one red-light stop. The activity page sample
    counter rose 37 to 210. Start assist caps throttle at 0.35, so the car cruised ~15.8
    km/h against a 30 km/h target; not changed.
  - **Town13 (experimental):** three runs loaded in ~2 min, warmed tiles, ran cameras
    120-150 s (cockpit 9-13 FPS, falling over successive runs; front 6-9, sides 2-3 per
    second) and exited cleanly. A straight 120 m route reached its destination with no
    safety event; a 200 m route stopped at the first sharp corner (~80 m) twice
    (collision, then lane departure). The policy's reference point is now 8 m ahead on
    every map (it was 32 m on Town13); this did not fix the corner.
  - **Follow-up, same day - "MODEL STOP - REALIGN MANUALLY" (seen by the user on Town13):** the
    car was stationary, the network braked, and it was more than 1.6 m off its lane or 15 degrees
    off heading, where start assist refuses to help, so it sat braked forever. New
    `app/cockpit/recovery.py`: after 3 s stationary and off route (and not a collision, obstacle
    or red light, which are deliberate stops) the cockpit puts the car on the nearest route
    waypoint ahead (within 40 m, spot free, at most 3 times per route); otherwise it says
    "TOO FAR / STILL OFF ROUTE - PRESS BACKSPACE". A displaced car (1.5 m sideways, 30 degrees,
    via `-DiagnosticDisplace "1.5,30"`) counted down 3-2-1, was re-aligned ("moved 1.8 m, turned
    -30 degrees"), waited for safe start and drove the route to waypoint 137/140. The status
    panel now wraps long messages instead of cutting them with "...".
  - **Countdown on the activity page:** the cockpit publishes `runtime.wait` (kind, label,
    elapsed_s, total_s) for the re-align wait and the safe-start wait; the page shows a thin
    yellow line plus "N s left" under its status text (built by a subagent; its tests and a
    loopback browser check at desktop and 375 px were run; I confirmed the live `/state` carried
    the cockpit's values during a run). Not checked: reduced-motion and screen-reader behaviour,
    and a view of the page during a real drive by me.
  - Offline: 238 tests pass; `verify_layout.py` passes. About a dozen
    CARLA sessions ran; thermal guard reported no fault, but there is no live temperature
    source and GPU 3D load was high.

## 2026-10-01

- Added `legacy run/run_large_map_neural.cmd`, which selects Town13 with the
  existing legacy policy and redesigned activity page. The legacy client sets
  nearby tile streaming, warms tiles under braking, and builds less dense map
  display/route graphs for Town11-13. This avoids a sibling runtime dependency.
  The first launch hit the previous 45-second RPC map timeout; raising only the
  large-map load timeout to 120 seconds allowed the retry to load Town13, warm
  tiles under braking, draw 75,074 road segments at 12 m spacing, load the saved
  model and route graph at 8 m resolution, connect the neural page, and exit
  cleanly after 25 seconds. The observed cockpit loop rate was about 4-7 FPS.
  A 960x540, 15 FPS retry remained in the Town13 load phase for over 17 minutes;
  it was interrupted and its owned CARLA processes closed. No destination route
  was selected. Town13 neural route movement is still unverified, and the
  combined mode is experimental until its low update rate and intermittent
  startup stall are resolved.

- Redesigned the existing neural activity page from the supplied references:
  green/yellow neurons, white weighted connections, red vehicle schematic,
  control diamonds and sampled decision history. Added raw/applied selection,
  freeze/resume and pointer/keyboard inspection. No model or control changes.
  Exact-forward-pass/HTTP regression and layout checks passed. Browser checks
  used recorded CARLA data on desktop and narrow layouts, including waiting,
  freeze/resume and disconnect. A new live CARLA trial was not needed for this
  display-only change. Preview is recorded telemetry, not a live driving claim.

- Added `legacy run/run_graphics_neural.cmd` for the existing policy and local
  activity page with Epic native CARLA graphics, full map layers, wind 65 and a
  20 FPS cap. The first live trial reached the model, webpage and route, then
  failed on the known RGB camera stall. Switched to the native 3D viewport and
  camera-free map cockpit. A 15-second repeat opened the page and exited cleanly
  at about 19.7 FPS. A 25-second route trial applied model outputs plus bounded
  assistance, reached about 27 km/h and exited cleanly; route completion is
  unverified. Safety and hardware checks stay active.
- Town13 manual Epic mode loaded, warmed nearby tiles, ran stationary at about
  28-29 FPS and exited cleanly. Full-map driving and later tile transitions
  remain unverified. No PC power or thermal limits were disabled.

- Renamed primary/secondary folders to laptop 1/laptop 2 and updated root tooling.
- Layout verification passed; localhost TLS rehearsal passed with toy physics.
- Original extracted client bundle passed integrity checks and 23 client tests.
- Configured encrypted read-only `Laptop2Transfer` share on laptop 1. Local TCP 445 check passed.
- Ethernet link observed at 100 Mbps. Laptop 2 address resolved to a peer MAC,
  but its TCP 445 test failed. Receipt of any package on laptop 2 remains unconfirmed.
- Added this project knowledge vault, agent reading/update instructions and portable
  copies for laptop 2. Obsidian is installed on laptop 1; opening this project vault
  in the app requires selecting the folder. No automatic Obsidian sync is configured.
- Physical TLS/CARLA tests, neural model integration and RL training remain pending.
- Share repair: laptop 2 reported that `Laptop2Transfer` did not exist, although
  laptop 1's `net share` listed that exact name and the expected transfer path.
  Prepared a `-Recreate` mode in `configure_file_sender.ps1` to recreate only this
  share, grant the sender account NTFS read/traverse access, refresh the scoped
  firewall rule and verify both ZIPs through SMB. The syntax check passed.
  The Windows administrator prompt was canceled, so the repair was not applied.
  Remote access and package receipt remain unverified.
- Share repair retry succeeded: `Laptop2Transfer` was recreated and reported Online.
  Sender account folder read/traverse access was granted; encrypted read-only share
  permissions were verified. The Ethernet firewall rule is enabled for TCP 445
  from exactly `169.254.102.28` to `169.254.41.109`. Both ZIPs were read through
  `\\169.254.41.109\Laptop2Transfer` locally and matched their source hashes.
  The receiving laptop must retry; package receipt there remains unconfirmed.
- Further SMB diagnosis: administrator-only logs confirmed laptop 2 reaches this
  host over TCP 445 but fails authentication. Security log substatus `0xc0000064`
  identifies an unknown username. Local user `medha` is Microsoft-account-backed;
  the successful local SMB check used the Microsoft-account identity. Prepared
  targeted receiver reconnection instructions. No server security downgrade was
  applied. Receiver authentication and ZIP receipt remain pending.
- Codex Control attempt: the user identified the receiver chat as `clarify claude request`.
  A remote connection was listed, but its chat list was unavailable and a remote
  app-server request expired while queued. The receiver chat could not be retrieved;
  no commands were executed on laptop 2. Reconnect the receiver control session
  before further coordinated repair. Sender SMB and ZIP verification remain valid,
  but receiver login and file receipt are still unverified.

