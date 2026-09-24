# Rendering notes

## Camera rendering

September 10 tests on an Intel Arc system repeatedly failed in the RGB camera rendering path under DX11 and DX12. Errors included D3D device loss and access violations in Unreal mesh gathering and render-target allocation. The underlying driver/engine cause remains unresolved.

Lower resolutions, reduced scenery, corrected capture pacing and renderer-thread options did not resolve those failures. A stock vehicle with four cameras also reproduced the problem. Speed and gear limits should not be treated as fixes for a rendering fault.

## Supported alternatives

`run_car.cmd` uses CARLA's native viewport for full-graphics manual driving. It has passed bounded driving checks without the extra RGB sensor cockpit.

`run_practice.cmd` uses map mode: fixed 0.05-second physics ticks, road geometry, instruments and manual controls, with scene rendering disabled and no RGB cameras. A bounded 90-second map/control check completed with cleanup and approximately 19-20 FPS. This does not evaluate neural driving quality.

The camera cockpit remains available for diagnostics. Missing or stale frames are reported, and managed startup checks CARLA RPC responsiveness rather than relying on an open port. Original world settings are restored during normal cleanup.

See [driving modes](TWO_MODES.md) for current controls and [maintenance](MAINTENANCE.md) for regression checks. Raw runtime logs are excluded from the repository.
