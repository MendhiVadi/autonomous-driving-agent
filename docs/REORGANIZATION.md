# Finish R1 and the reorganized project

## Checkpoint

The complete pre-change file backup is:

`C:\Users\medha\Documents\Autonomous Driving Backups\Finish R1-20260913-095714`

It contains **92,812 files / 49,046,659,137 bytes**, including the entire
original workspace and `Documents\CARLA`: simulator binaries, downloads,
Python environment, custom code, datasets, model files, logs, screenshots,
notebooks and earlier backups. Every copied file was SHA-256 checked against
its source before the project was changed. `manifest.jsonl` records the
original paths, backup paths, sizes and hashes. Verification finished on
September 13, 2026. `FINISH_R1.json` in the working project records the backup
location and manifest hash.

Git tag **`Finish-R1`**, commit **`d952650`**, preserves the original project
checkpoint. The full file backup also preserves the four original custom
Python files that used to live inside the simulator installation.

To restore, close running sessions, copy the backup into separate empty
folders, and verify the files against the manifest before replacing any
working directory. Do not merge old files into this reorganized tree: that
would recreate duplicate import paths. Restore the CARLA-side custom files
from the same snapshot. Its virtual environment retains the original
base-interpreter path. The backup is a file snapshot, not a Windows image.

## Organization

The top level now presents four everyday commands: `run_practice.cmd`,
`run_training.cmd`, `stop_stack.cmd`, and `verify.cmd`.

- `app/` owns all custom driving code, including cockpit, vehicle controls,
  manual transmission, neural inference, safety and local visualization.
- `tests/` holds regression tests; `tools/` holds training, packaging and
  validation utilities. `requirements/` holds the dependency snapshots.
- `scripts/` holds PowerShell launch/setup scripts. `run/` holds secondary
  launchers and the existing `_practice.cmd` entry point.
- `docs/` holds documentation and diagrams. Historical cockpit screenshots
  are in `artifacts/screenshots/`; historical root logs are in `logs/archive/`.
- Demonstrations, exports, model files, earlier backups and research outputs
  remain on disk. Generated data and local agent settings are excluded from
  new Git commits; they remain available in the Finish R1 checkpoint.

The four Python files in the CARLA installation are now compatibility adapters
to `app/`, preventing independent edits to competing source copies. The old
README is retained under `docs/archive/` as historical evidence, while the
short root README describes the current commands and limitations.

## Safety repairs

| Problem | Resulting behavior |
| --- | --- |
| Negative lane departure could bypass the stop comparison | Departures on either side trigger braking |
| Missing telemetry silently supplied safe-looking defaults | Missing, malformed or non-finite safety telemetry triggers full braking |
| NaN/infinity could survive clamping or disable deadlines | Controls, policy inputs and watchdog limits reject invalid values |
| Cockpit safety depended on its own loop continuing | Independent watchdog brakes when control publication stalls |
| Terminal client retained throttle while waiting for input | Independent watchdog, bounded input, collision sensing and safety arbitration |
| Failed emergency-brake callback was silently discarded | Failure is logged and retried while the command remains stale |
| Initialization or one cleanup failure could leak actors | Post-spawn setup is covered by cleanup; each cleanup action is attempted |
| Launcher shutdown swept every matching CARLA process | Practice stops its owned process tree; new sessions refuse unowned processes |
| Simultaneous managed launchers could race | Practice and supervised mode share a Windows session mutex |
| Stop command killed broadly matched process trees | It requests cleanup from this project's supervisor and reports timeout |
| Hardware-event query failures were treated as all-clear | An unavailable or malformed event log blocks preflight |
| Short query window could miss an active cooldown | The query covers at least the longest configured cooldown |
| Optional gesture receiver could bind beyond loopback | Non-loopback binding and invalid expiry values are rejected |
| Browser requests trusted arbitrary Host/Origin headers | Local visualization rejects unexpected hosts and cross-origin requests |
| Map installer extracted unvalidated archive paths | All paths are validated before writing; only map content is extracted |
| Recorder names could escape their output directory | Path-like names and non-finite JSON records are rejected |
| Setup and launcher commands could mask failed exit codes | Everyday launchers preserve failures; dependency setup checks each result |
| Direct-link setup removed all existing static addresses | Conflicting addresses or a default route are reported without deleting them |
| Implicit Windows text encodings corrupted labels | Python text reads/writes use UTF-8 explicitly; labels were restored |

The firewall setup script now defaults to the direct Device 1/Device 2
addresses instead of every remote host on a Private network. No firewall
rules were applied and no dependencies were installed during this cleanup.

## Verification

- Original baseline: **131 tests passed**.
- Expanded regression suite: **150 tests passed** after reorganization,
  notebook regeneration and encoding repairs. Run `verify.cmd` to repeat it.
- Python compilation and PowerShell syntax checks passed.
- The real additional-map archive passed a dry run: **23,043 validated
  entries**. No map assets were extracted.
- A **90-second live session** through `run\_practice.cmd` travelled
  **208.23 m**, reached **27.67 km/h**, and used **zero RGB cameras**.
  **348 fresh activity snapshots** matched the saved network's calculations
  exactly, with zero activation mismatches. The policy hash was unchanged.
  The launcher returned exit code 0 and its simulator/driver processes exited.
- A separate preservation check compared **100 protected files** against
  the backup, with **zero changes**.

Evidence: `logs/finish-r1-tests-final.log`,
`logs/finish-r1-live-launcher.log`, `logs/finish-r1-live-monitor.json`, and
`FINISH_R1.json`. The live trial preceded the final text-encoding cleanup;
offline regression checks cover the final source.

## Remaining limits

This is a tested restructuring and repair of the identified unsafe code
boundaries, not a proof that every possible defect has been eliminated.
The cockpit remains a large module that can be split further as features
change. Four-camera rendering remains unreliable on this machine. The saved
policy remains preliminary and assisted; the live trial does not establish
general traffic-law compliance or unseen-map reliability.

The separate supervised neural mode still requires `nn_policy_colab.json`.
The prepared remote-client launcher has not been verified across two devices;
it is not an implemented authoritative Device 1 gateway for remote commands.
No weights were trained or replaced, no data was uploaded, and no external
service was changed.
