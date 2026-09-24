# Map support

| Map | Status |
| --- | --- |
| Town02_Opt | Default for manual driving and initial connection tests; bounded gateway reset/step checks passed |
| Town13 | Short stationary manual check passed; gateway map loading and tile warm-up remain intermittent |
| Tartu | Windows compatibility is unverified |

CARLA maps are external dependencies and are not distributed in this repository. Use maps compatible with CARLA 0.9.16. `tools/audit_maps.py` can inspect an installed map against its retained archive.

`run_large_map.cmd` selects Town13 for manual diagnostics. Large-map startup keeps full rendering enabled, bounds nearby tile streaming and warms tiles with the vehicle braked. It can still stall; use Town02_Opt for the first two-PC connection. Do not start another client during initialization.

See [validation notes](VALIDATION.md) for the limits of the recorded checks.
