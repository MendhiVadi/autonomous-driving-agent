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

