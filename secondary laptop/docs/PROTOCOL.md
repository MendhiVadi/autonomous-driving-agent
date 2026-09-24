# Reset/step protocol v1

Each application owns a separate ordinary-file implementation of this wire
contract. There are no shared imports. A root maintenance tool tests
interoperability by starting independent processes.

## Transport and authority

UTF-8 JSON followed by one newline, maximum 16,384 bytes including newline.
Exactly one request may be outstanding. Duplicate JSON keys, extra fields,
nonfinite actions, unexpected versions, and pipelined frames are rejected.
Plaintext connections are limited to literal 127.0.0.1. For development, set a
fresh random secret through SIM_GATEWAY_TOKEN and never commit or log it.
Private IPv4 operation requires TLS 1.2 or newer plus an explicit allowed peer.
The client validates the paired self-signed certificate, its validity dates,
the fixed server identity carla-sim-host, and the exact certificate SHA-256
before sending its authentication token. System CA trust and SSLKEYLOGFILE are
not inherited. Wildcard/public bindings and unencrypted LAN calls are refused.
Pairing material is generated once in protected, Git-ignored credentials
folders. Only the public server certificate and client token are copied to the
client; the server private key remains on the host. TLS does not replace
physical link/firewall validation or traffic-safety evaluation.

The first request has version=1, type="hello", and token. The response has
version, ok, session, sequence=0, nonce, lease_seconds, and result. Session and
nonce are unpredictable 32-character hexadecimal values. Normal requests
contain exactly version, session, sequence, nonce, operation, payload.
Sequence must increase by exactly one and the nonce must match the most recent
reply; each successful reply replaces it. All timing is measured on the host.
The default next-command lease is two seconds. Complete frames, not first
bytes or client timestamps, must arrive before expiry.

Only one client controls the environment at a time. Malformed commands,
connection loss, missed deadlines, or environment errors invalidate the episode
and apply braking. Reconnect then reset; there is no transparent command retry,
session takeover, heartbeat that perpetuates old controls, or model fallback.

The gateway alone ticks a synchronous world. While a bounded reset/map load or
physics step is in progress, the next-command lease is suspended: no second
client or queued command can advance physics. It is rearmed after a response.
A stalled normal physics RPC is bounded by five seconds (three in manual mode);
a gateway map-load RPC by 90 seconds. Large-map initial tile warm-up is
brake-held and may use one 60-second tick then three 10-second ticks. The client
allows up to 180 seconds per reply for initialization; this is not the much
shorter next-command lease. Manual map initialization may take 120 seconds.
These are development safety measures, not a guarantee against simulator or
operating-system failure. No asynchronous/free-running CARLA mode is supported.

## Operations

- reset: payload has seed (integer 0..2147483647), scenario, max_steps (1..20000).
  Reply result contains observation and info. A seeded route/spawn is chosen;
  global traffic phase/bitwise simulator determinism is not promised.
- step: payload has throttle [0,1], brake [0,1], steer [-1,1]. Booleans do not
  count as numbers. Reverse is not supported in this first curriculum.
  Result contains observation, reward, terminated, truncated, info.
- close: empty payload; applies brake and returns closed=true.

Observations: speed_mps, lateral_m, heading_error_rad, progress_m,
route_length_m, speed_limit_mps, obstacle_distance_m (all finite numbers);
stop_required, collision, offroad (booleans). Progress follows an ordered
route, not total distance driven. No cameras or neural features are transferred.

Info records requested_action, applied_action, interventions, step, reason,
and reward_parts. Throttle is capped at 0.4, steering at +/-0.7, braking takes
priority, and a conservative 8.33 m/s ceiling applies even on faster roads.
Traffic/hazard guards use backend measurements; missing perception is not
magically supplied by this contract. In particular the first CARLA adapter is
empty-road only and reports obstacle distance as a clear-range sentinel. It
must not be used for traffic or pedestrians without implementing perception.

## Episode and reward boundaries

Collision/off-route/wrong-way terminate before route completion can award a
bonus. Step/time limits and 200 no-progress steps truncate. Waiting at a red
signal is exempt from the no-progress counter but still has a finite episode
limit. Positive progress is paid only above the furthest previously reached
route position, so retracing does not repeatedly earn reward. Large progress
jumps fail closed.

Rewards include new progress, elapsed-step cost, lateral error, speeding,
interventions, and terminal outcomes. They are provisional and incomplete.
No learning starts from these engineering tests, and training_ready is false.

The toy backend supports lane_follow, red_light and obstacle fixtures. The
CARLA backend supports lane_follow on a short same-lane non-junction segment,
with a collision sensor and basic existing traffic-light trigger check. Stop
signs, signal stop-line evaluation, dynamic obstacles, sensor-frame alignment,
complex navigation, full evaluation scenarios and framework wrappers remain
required before meaningful RL training.
