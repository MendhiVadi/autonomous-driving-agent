# Pre-connection validation — updated 2026-09-24

## Reliability and maintenance update — 2026-09-24

- Unsupported CARLA scenarios now reject the session without marking the host
  as failed. A new connection can reset an empty-road episode.
- Emergency-brake failures during disconnect cleanup reach the launcher as
  fatal errors. The first environment failure remains available for diagnosis.
- Client bundle verification rejects empty/incomplete manifests, missing or
  changed files, malformed paths/hashes, extra source or credentials, and server
  private keys. Generated runtime output is excluded from the source check.
- Layout scanning prunes excluded folders before descent. Seven alternating
  measurements on this workspace reduced median traversal from 0.233 s to
  0.025 s and total audit time from 1.079 s to 0.852 s. These are local maintenance
  timings, not simulator performance measurements.
- Offline checks: 81 host tests, 23 client tests and all 179 legacy tests passed,
  including the publication portability changes. The legacy visualizer test
  now uses a deterministic model fixture instead of a private exported policy,
  and the core tests resolve CARLA from the configured installation.
- The refreshed 20-file private client bundle passed manifest checks, all 23
  client tests and three encrypted toy scenarios after extraction in isolation:
  `handoff/secondary-pc-20260924-235514-556510.zip` at the workspace root.
  SHA-256: `b8a58f9032a9b6f8260258fc20e73d8cebaa968ca89016e2bc45df65c653f24a`.

These changes were checked offline and through local sockets. No CARLA session
was started during this maintenance pass; the earlier live-test boundaries below
still apply.

## Latest preparation update — 2026-09-24

- Town13 asset audit: all 339 selected files match retained archive size/CRC.
- Isolated host Python 3.12.10 with the official locally bundled CARLA 0.9.16
  wheel; no network dependency download, learning framework or legacy runtime change.
- Native Python 3.11 CARLA fault isolated through Windows crash records. A
  clean app-owned map cache, bounded hero tile streaming and initial brake-held
  warm-up are in place. Ineffective shipping-build map arguments were removed.
- Town13 live manual check passed: eight seconds after initialization, no
  input/motion, Epic graphics, wind 65, 23.7 FPS measured while stationary,
  clean exit. Log: `logs/20260924-010114-driving.log`.
- Town13 gateway retries still stalled at initial tile warm-up and map load
  (`logs/20260924-010808-driving.log`, `logs/20260924-011512-driving.log`).
  The cause of these intermittent stalls remains unresolved. The manual result
  is not evidence of reliable gateway operation; keep Town02_Opt as the baseline.
- Live encrypted Town02_Opt gateway check passed after the final runtime fixes:
  seed 7, 44.0034 m route, reset and five brake-held steps, no collision/off-road
  flags, ending at the step limit. Rendering stayed enabled, wind was 65 and
  physics step was 0.05 s. Both client and managed launcher exited successfully.
  Host log: `logs/20260924-070423-driving.log`. No driving-quality claim follows.
- TLS 1.2+ with paired-certificate trust, fixed server hostname, exact leaf
  certificate matching, token authentication and an exact peer allowlist.
  Plaintext LAN/public/wildcard binding remains forbidden. No firewall or
  adapter changes have been applied.
- Pairing files are protected for this workspace's Windows owner, the creating
  sandbox account and SYSTEM; the server private key is excluded from the bundle.
- The client ZIP was extracted into a temporary independent folder and its
  manifest, 12 client tests and three encrypted toy scenarios passed. It loads
  no simulator, training code, or files from a sibling application.
  Final verified package: `handoff/secondary-pc-20260924-070711-616940.zip`
  at the workspace root; 19 packaged files, no server private key.
  SHA-256: `57a6612065d4f8f53eb9f56921ac5dddeda3d2ed2ab6ca0fe78b112deecc2384`.
- Final offline checks: 79 host tests, 12 client tests, 179 retained legacy
  tests: **270 passed**. Legacy checks ran with the simulator stopped so the
  intentional one-session lock could be tested correctly. Layout checks passed
  for 100 Python files, 189 local imports and 20 documentation links. All six
  current PowerShell scripts passed syntax parsing; the host import/map
  preflight also passed. A mixed PowerShell 5.1/7 module-path compatibility
  issue in pairing-directory permissions was corrected and retested.
- Final read-only cleanup check found zero simulator/gateway processes and
  zero listeners on the test ports (2000 and 8765).

Physical two-PC routing, firewall, cable-pull recovery, latency, sustained
rendering/driving, and second-PC hardware remain unverified. No model training
or file deletion has occurred. See [connection checklist](CONNECT_SECOND_PC.md)
and [map details](MAPS.md). The earlier section below is retained as history.

No reinforcement-learning run, optimizer, framework installation, model
initialization, checkpoint creation, or data-collection run was started.
No existing user files were deleted and no model weights were edited.

## Historical checkpoint — 2026-09-23

The remainder of this document records the earlier localhost-only checkpoint;
its transport restrictions and test counts are superseded by the update above.

### Passing checks

- 60 host tests, including real localhost socket failure/replay/timeout checks.
- 10 independent client tests, including lost-response no-retry behavior.
- 179 retained one-laptop regression tests, unmodified in this pass.
- Total: 249 tests; 50 more than the previous 199-test checkpoint.
- Root maintenance rehearsal: two isolated Python processes, three toy
  scenarios, 12 fixed-control steps each. Passed despite a deliberately
  unrelated inherited PYTHONPATH, because each entrypoint uses isolated Python.
- Layout check: 92 Python files, 177 local imports, 13 documentation links.
- Windows PowerShell parser checks and managed gateway import preflight.
- Live CARLA Town02_Opt: seed 7, 44.0034 m same-lane route, reset and five
  brake-held steps. Ended by step_limit, then session close and owned-process
  shutdown. No collision/off-road flags during those steps. This establishes
  reset/step connectivity, not driving quality, traffic safety or RL readiness.
  Host log: `logs/20260923-192046-driving.log`.

The live Town02 check preceded the last small additions (backend metadata and
unexpected-actor rejection); those additions have dedicated offline adapter
tests. Full-graphics launch settings and wind 65 remain enabled. No visual
quality, driving performance, or sustained frame-rate claim is made here.

### Map boundary at that checkpoint

Town13 appears in the installed assets and CARLA's available-map list, but the
Epic-profile live load exceeded the bounded 90-second map-load RPC. The
launcher cleaned up its simulator processes. Cause not established; usable
large-map performance is still pending. Host log:
`logs/20260923-191715-driving.log`.

An older completed Tartu transfer was finalized to its 1,577,425,960-byte
archive. The SHA-256 was recorded; it was not installed over the working
simulator. See [map notes](MAPS.md) for source and compatibility restrictions.

### Work pending at that checkpoint

Secure LAN transport/certificate setup; real firewall/link/disconnect testing;
second-PC hardware/dependency setup; traffic/sign/stop-line and dynamic-hazard
coverage; collision-frame validation; deterministic evaluation scenarios;
reward calibration; framework wrappers/spaces; trainer and checkpointing.
The development gateway intentionally refuses non-loopback addresses.
