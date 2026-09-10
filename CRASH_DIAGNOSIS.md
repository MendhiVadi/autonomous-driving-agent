# CARLA crash investigation — 2026-09-10

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
