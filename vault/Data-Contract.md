# Data contract

Source: protocol v1 in laptop 1 and laptop 2 `docs/PROTOCOL.md`.

## Observation: laptop 1 to laptop 2

| Field | Meaning |
| --- | --- |
| `speed_mps` | Vehicle speed in metres per second |
| `lateral_m` | Lateral route/lane error in metres |
| `heading_error_rad` | Heading error in radians |
| `progress_m` | Ordered route progress in metres |
| `route_length_m` | Route length in metres |
| `speed_limit_mps` | Speed limit in metres per second |
| `obstacle_distance_m` | Obstacle distance; current empty-road CARLA adapter uses a clear-range sentinel |
| `stop_required` | Boolean stop requirement |
| `collision` | Boolean collision flag |
| `offroad` | Boolean off-road flag |

No camera frames or intermediate neural activations are transferred by this contract.
A future model must define its input selection, order and normalization explicitly.

## Action: laptop 2 to laptop 1

`throttle` and `brake` are finite numbers in [0,1]; `steer` is in [-1,1].
Reverse is not supported by this first curriculum. Host guards cap throttle at
0.4 and steering at +/-0.7, give braking priority and apply a conservative
8.33 m/s ceiling. Requested and applied actions can differ.

Each step returns observation, reward, `terminated`, `truncated`, and `info`.
Info includes requested/applied actions, interventions, step, reason and reward parts.
Reward design is provisional and `training_ready` is false.

## Delivery and interruption

Messages are newline-delimited UTF-8 JSON, at most 16,384 bytes including newline.
TLS 1.2+ and certificate verification precede authentication on the LAN.
Session, sequence and nonce checks protect ordering. The default next-command
lease is two seconds; bounded reset/step execution suspends that lease.
Initialization reply timeout and command lease are different limits.

On malformed commands, connection loss or lease expiry, the episode is invalidated
and the host applies braking. Reconnect and reset; do not retry an uncertain action.
Verify the actual physical cable-pull behavior before relying on the connection.

## Legacy neural website — 2026-10-01

This is a separate read-only loopback display. `/state` supplies model sizes and
weights, plus `sample.sequence`, `sample.time`, all activation layers, server
`now` and the latest `runtime` fields. Input labels retain the policy's eight
features; raw outputs are steering, accelerator and brake. Applied controls
come from `runtime.applied` and can differ because of assistance and safety.

The page samples up to 10 Hz and keeps ten recent browser snapshots at up to
three per second, appending only on a new inference sequence. Timeline seconds
start at the first received sample; delta means the change in steering between
displayed snapshots. This is not a complete decision log or a guarantee that
runtime telemetry is atomically paired to the forward pass. Colors saturate at
activation +/-1 and control fills at actuator bounds; numeric values retain the
raw prediction. The red car is a schematic, not a camera feed.

## Legacy three-camera cockpit — 2026-10-06

No camera pixels reach the policy: front/left/right feeds are display only, and the model
still receives its eight state features and returns steering, accelerator and brake. The
reference waypoint behind its lane/heading/curvature features is 8 m ahead on the route on
every map (previously a fixed four waypoints, which was 32 m on Town13). The `/state` page
contract above is unchanged. The cockpit log adds a `[drive]` line every 2 s (speed, gear, yaw,
applied throttle/brake/steer, focus, route progress) and the safety supervisor's reasons
(`collision`, `lane_departure`, `red_light`, `stale_command`) still override the policy.
`runtime.wait` (new, optional, from `publish_runtime`) is `null` or `{kind: start|realign|exhausted,
label (<= 40 chars), elapsed_s, total_s}` and drives the yellow countdown line on the activity page; the
server sanitises it (unknown kinds dropped, numbers clamped, non-finite removed). The page shows it
only while samples are live. `--scripted-keys`, `--diagnostic-yaw-offset`, `--route-ahead-m` and
`--diagnostic-displace` are diagnostics, not part of any contract. Camera sizes: front 320x180, sides 256x144 (widths must be multiples of 64).
