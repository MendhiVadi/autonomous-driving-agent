# CARLA crash investigation — 2026-09-10

## 2026-10-06 update: RGB cameras work under DX12, not DX11

Bounded probes (own server, Town02_Opt, Epic, offscreen, Intel Arc 140V, driver
32.0.101.8132) separated the camera stall from the cockpit. Under **DX11**,
every camera trial lost its stream and all RPC within 1-10 s of the first
frames; teardown calls only succeeded later, after the probe had stopped its sensors:

| Trial (DX11 unless noted) | Frames before the stream stopped |
| --- | --- |
| Cockpit setup: 3 cameras, 960x540 main view | 31 front |
| One 320x180 camera only | 14 |
| 320x180 main view | 56 |
| Synchronous client ticks | 1 per camera |
| Low quality | 176 (~10 s) |
| Variable timestep at ~72 server frames/s | 11 |
| Camera post-processing disabled | 24 |
| **DX12**, variable timestep | **403 front, no stall in 40 s** |
| **DX12**, 120 s soak | **1,192 front (9.9 fps), 238 per side, 0 RPC failures, max RPC 797 ms** |
| **DX12**, 15/5/5 fps, 60 s | 14.9 / 5.0 / 5.0 fps, max RPC 31 ms |
| **DX12**, synchronous 15 Hz client ticks, 60 s | 10.4 / 3.5 / 3.5 fps, max RPC 16 ms, GPU 3D ~44% vs ~66% free-running |

Main-view size, quality level, post-processing, pacing and synchronous ticks
did not fix DX11. The server also free-runs at 70-90 frames/s in asynchronous
mode (`t.MaxFPS` had no effect through this launch path), which is why the
three-camera cockpit now owns 15 Hz synchronous ticks. GPU load stays high, so
the thermal guard still matters; no live temperature source exists on this PC.

**Sheared side feeds.** A 240x135 camera returns a buffer of the correct size
(129,600 bytes) whose rows are shifted (best-fit stride 224 px; adjacent-row
difference 5-6x the 320x180 front feed). 192, 256, 320 and 640 px widths were
clean in every run. The cause is the GPU read-back row alignment: rows whose
`width x 4` bytes are not a multiple of 256 are misaligned. It was never a
Python copy problem. `readback_safe_size()` now rounds camera widths to a
multiple of 64 px, so the side cameras are 256x144.

`run_practice.ps1` therefore defaults the camera profiles (`triple`, `parking`,
`safe`) to `-RenderApi dx12`; an explicit `-RenderApi` still wins and the native
single-window map profile keeps its verified DX11 path. The older September
DX12 crash evidence below used different settings and is not contradicted:
this is a bounded result for three Epic offscreen cameras on this machine.
Evidence: `tools/render_probe.py` (the harness) and the per-trial result files in
`logs/render-probes-20261006/`.

## Lightweight 3D follow-up

The user requested the smallest practical 3D town with vegetation and weather
removed. `run_light_3d.cmd` now selects Town02_Opt with a single 320x180 front
camera, Low graphics, clear dry daylight locked (C disabled), and the Foliage,
Particles, Props, StreetLights and Decals layers omitted. Buildings, Ground,
Walls and ParkedVehicles remain. No moving traffic is spawned.

The initial asynchronous run exceeded the requested camera rate (up to 45.1
updates/s). Low-scenery mode now owns synchronous 0.05-second ticks capped at
20 Hz, and the launcher also requests `t.MaxFPS 20`. The corrected live run
confirmed display rates of 19.5-19.8 FPS and front-camera rates of 9.2-10.2 FPS.
It still crashed with D3D device lost / `0x887A0020 INTERNAL_ERROR` at 46 seconds
of server uptime. Removing foliage and weather and correcting capture pacing
did not resolve the Intel Arc rendering fault. The failed session was stopped;
no CARLA or cockpit processes remained after cleanup.

Evidence: `logs/light-3d-paced.log`, `logs/light-3d-paced.error.log`, and
`logs/practice-safe.png` (a startup screenshot, not proof of continuing health).
The preceding foliage-free asynchronous run is recorded in
`logs/light-3d-no-foliage.log` and `.error.log`. All 78 current core tests pass;
PowerShell parsing passes. Original files are in `backups/20260910-light-3d/`.

The usable workaround is `run_practice.cmd`: a live map with manual controls,
scene rendering disabled, and no RGB sensors. The user explicitly accepted
this mode while the camera-rendering fault remains unresolved.

## What the evidence shows

- The initial stale server was PID 8812. It was still present after crashing,
  but a real CARLA RPC request timed out. Its latest crash report recorded
  `DXGI_ERROR_DRIVER_INTERNAL_ERROR (0x887A0020)` after 83 seconds, despite
  DX11, a 160×90 viewport and a 10 FPS cap.
- Multiple September 10 crashes occurred under both DX11 and DX12. This is
  not evidence that a specific road speed or gear causes the native failure.
  [Microsoft's error definition](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/dxgi-error)
  describes a driver failure putting the device into the removed state.
- The bundled matching PDB resolved repeated access violations to
  `FSkeletalMeshSceneProxy::GetMeshElementsConditionallySelectable`,
  `SkeletalMesh.cpp:5127`, through dynamic-mesh gathering and
  `FDeferredShadingSceneRenderer::Render_CARLA`. Other stacks resolved to
  D3D11 texture creation and render-target allocation. This localizes the
  failure path; it does not establish whether the underlying defect belongs
  to Unreal, a particular asset, the driver, or their interaction.
- Disabling the RHI thread and running the engine single-threaded both failed
  live camera validation. A separate stock Tesla/four-camera probe also
  failed. The custom six-speed gearbox is therefore not necessary to
  reproduce a renderer crash.
- Vulkan failed immediately with `VK_ERROR_OUT_OF_HOST_MEMORY` in its swap
  chain initialization. NullRHI also crashed on startup in this Windows
  package. Neither option was installed as the default workaround.
- The installed GPU was Intel Arc 140V, driver `32.0.101.8132`. No driver,
  registry timeout, power policy, or operating-system setting was changed.
  The thermal guard reported no current blocking thermal/hardware event.

## Implemented changes

- `spawn_car.py` in the CARLA installation now supports `--camera-profile map`.
  It keeps physics, road geometry, nearby actors, instruments, manual gears,
  steering, brakes, reverse, and the destination map. Camera-based perception
  is unavailable in this mode.
- Map mode owns synchronous simulation ticks, with one 0.05-second step per
  control frame and a maximum 20 FPS. Physics uses 0.01-second substeps. This
  prevents an unrendered asynchronous world from racing ahead of its control
  loop. Original world settings are restored on normal exit.
  [CARLA timing documentation](https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/)
  explains fixed timesteps and consistent substepping.
- The diagnostic parking profile now has four distinct rigid cameras. The
  former implementation copied the front image into every panel. Camera
  startup is logged, and missing/stale images produce an error instead of
  indefinitely displaying a frozen cached image. This profile remains
  **unverified for reliable use on this machine**.
- `run_practice.ps1` defaults to map mode, checks actual RPC/world liveness,
  prevents concurrent local cockpit/supervisor processes, checks the thermal
  guard, logs server/cockpit output, and cleans up an owned server even if
  readiness fails. `run_device1_ui.cmd` uses this same managed entry point.
- The supervisor now checks CARLA RPC responses and asynchronous world ticks;
  a listening TCP port alone no longer reports a frozen server as healthy.
- Existing gear ratios and speed/steering limits were preserved. They should
  not be described as a cure for the renderer fault.

## Validation and limits

- 102 existing/regression tests passed, including new cases for a listening
  but dead RPC service, a stalled asynchronous world, and a healthy world.
- An initial nearly three-minute map run retained roughly 20 FPS, had no
  renderer crash, and removed all actors. Its rule-based route test drove
  off-road and failed the movement threshold; this was not an autonomy pass.
- Final paced map/control test: 89.9 seconds of runtime, 88.3 simulated
  seconds, 1,784 world-frame advances, 35.1 m accumulated movement, 5.0 km/h
  peak speed, process exit 0, and zero remaining vehicles/sensors. The UI
  stayed around 19–20 FPS. See `logs/map-paced-validation.json` and `.log`.
- The control test uses off-screen SDL drawing and a bounded forward/brake/
  reverse sequence, so keyboard activity cannot interrupt it. It does not
  train or evaluate the neural policy or establish high-speed stability.
- Fresh-launch verification passed through `run_practice.ps1`: it started an
  owned server, loaded Town05, displayed map mode for 12 seconds at 19.7 FPS,
  and stopped the server cleanly with exit code 0. Evidence:
  `logs/practice-20260910-134133-cockpit.log` and `logs/practice-map.png`.

Camera rendering remains unresolved. The deployable `nn_policy_colab.json`
is also absent; the existing neural launcher correctly refuses to substitute
legacy or synthetic weights. No model weights or training episodes were changed.

Original edited runtime files are retained under
`backups/20260910-crash-fix/`; the review diff is `logs/crash-fix.patch`.
