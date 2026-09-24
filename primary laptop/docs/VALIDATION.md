# Validation

## Maintenance checks, September 24-25, 2026

All 283 offline tests passed: 81 host, 23 client and 179 legacy tests. The client package was extracted into a separate temporary folder, checked against its manifest, and exercised through three encrypted toy scenarios. Raw logs, private packages and credentials are excluded from the repository.

The latest fixes cover unsupported CARLA scenario rejection, disconnect braking errors, incomplete package manifests and portable legacy test fixtures. The layout audit checks source isolation, Python syntax, local imports and documentation links. Folder traversal now prunes excluded output and environment directories; local measurements reduced median scan time from 0.233 s to 0.025 s and total audit time from 1.079 s to 0.852 s.

These maintenance checks use local sockets and test doubles. They do not measure CARLA driving performance.

## Earlier CARLA checks

On September 24, the Town02_Opt TLS gateway completed a seeded reset and five brake-held steps on a 44 m same-lane route. Rendering remained enabled, wind intensity was 65, and the physics step was 0.05 s. The client and managed launcher exited successfully.

Town13 completed an eight-second stationary manual session with Epic graphics at approximately 23.7 FPS. Subsequent gateway starts stalled during map loading or tile warm-up, so Town13 remains experimental.

## Remaining validation

Physical two-PC routing, firewall configuration, cable-pull recovery, latency, sustained rendering and driving still need testing. Traffic perception, collision-sensor timing, reward calibration, trainer integration and policy evaluation remain open work.
