# Maintenance and reorganization

## Scope (2026-09-23)

The baseline was 159 passing offline tests. Existing local source edits, data,
models, backups, and the CARLA installation were preserved. Source relocations
retain content; no additional source or model was discarded in this pass.

## Completed changes

1. Group application modules into vehicle, simulation, runtime, learning,
   telemetry, and cockpit packages. Keep established command entry points.
2. Extract the legacy policy and observation helpers from the driving runner;
   extract cockpit input, navigation, and argument handling from its session.
3. Centralize machine paths and legacy policy selection. Keep current rendered
   and lightweight settings intact.
4. Fix bounded-angle computation and avoid repeatedly serializing unchanged
   network weights in the activity endpoint.
5. Repair documentation and add a read-only repository check for missing local
   links and Python import targets. Run regressions and command smoke checks.

After the user's isolation requirement, the entire existing application,
models, datasets, outputs, local backups and launchers were relocated into
`legacy run/`. The new primary host has independent copies of the small
manual driver and safety/lifecycle helpers. No application loads another's
source, weights or settings. Only external third-party CARLA binaries and
installed libraries are reused.

The cockpit's input, navigation, configuration and graphics helpers now have
explicit owners. Its remaining session orchestrates the current UI. Model
loading validates and reads the JSON artifact once; the activity endpoint
caches serialization of unchanged weights. Huge finite angle values are
normalized in constant time. These remove identified waste; no overall neural
driving speedup is claimed without a controlled performance comparison.

## Verification

- 162 legacy regression tests passed from the relocated directory.
- Eight primary-host offline tests passed, covering graphics arguments, steering, world
  ownership, cleanup and watchdog behavior.
- The layout checker validates Python syntax, local import targets,
  cross-application references, independent files and documentation links.
- Isolated-process import checks loaded 34 legacy modules and six host
  modules with no sibling source files.
- Immediately after relocation, all 338 protected data/output files matched
  their original SHA-256 hashes (110,298,043 bytes).
- Legacy live smoke: 10 seconds, Town02_Opt, its local saved policy, 976 road
  segments, destination map visible, approximately 19.7–19.8 FPS, then shutdown.
- Primary live smoke: 10 seconds, full graphics, wind 65, approximately
  25.5 FPS stationary, then shutdown. The initial host attempt timed out;
  correcting the switch/value quoting to match the original launcher allowed
  the retry to start. Neither live test evaluated an autonomous route.
- A final five-second host session passed with process-handle cleanup and
  exit code zero; no simulator processes remained. All 69 model, notebook,
  contract and training-data files were hash-checked again after live testing
  with no changes.

The legacy smoke test refreshed the launcher's existing generated
`logs/practice-map.png`. Screenshot output now includes the run timestamp
to avoid replacing that latest-image file on subsequent launches. Dataset
and model files were not changed.

## Edge-case hardening (2026-09-23)

The follow-up audit reproduced failures before changing behavior:

- Watchdogs now cover a missing first command, reset their trip state on
  restart, retain ownership of callbacks still running after stop's timeout,
  and reject non-callable callbacks. Link health requires both a received
  command and heartbeat. These fixes are independent copies in each app.
- Model loading rejects malformed JSON structures/metadata, boolean weights
  and numbers too large to represent. Inference rejects invalid inputs and
  overflowing intermediate activations before a nonlinear activation can
  disguise them.
- Recovery assistance validates all eight inputs and its timers/limits.
  Invalid input produces a braking result with assistance disabled.
- Manual steering rejects invalid direction/timing/numeric values and also
  clamps out-of-range prior steering while recentering.
- Default model candidates must resolve inside this application and cannot
  be hard-linked files. The PowerShell launcher uses the same Python resolver.
- Bad recorder options fail before opening an episode file. Flush failure
  still closes the handle.
- The primary launcher's Windows PowerShell 5.1 path treats startup stderr
  as retryable and logs ordinary client stderr without terminating a healthy
  session. Real nonzero exits still fail. Isolated Python mode ignores
  inherited PYTHONPATH values.

Validation: 179 legacy tests and 20 primary tests passed, including 29 added
regressions. Layout/import isolation and PowerShell syntax checks passed.
The actual primary CMD launcher completed a five-second full-graphics session
and exited with code zero; evidence is in its own
`logs/20260923-185621-driving.log`. No RL training or remote-command testing
was performed. No additional files were deleted and no model weights changed.

## Product direction

This laptop owns CARLA, graphics, physics, and final safety enforcement.
`laptop 2/` is the future reinforcement-learning training/inference
workspace. RL starts from scratch. The existing imitation model is a retained
baseline, not the initializer for RL. Finished remote-policy driving must use
full scenery, shadows, and wind-blown foliage on this laptop.

## Verification boundary

Rendered remote-policy operation, two-device recovery, and RL performance
still need implementation and live evidence. No cross-device runtime or RL
trainer exists yet. A longer session/rendering split of the preserved cockpit
can be evaluated separately; the new host does not import that cockpit.
