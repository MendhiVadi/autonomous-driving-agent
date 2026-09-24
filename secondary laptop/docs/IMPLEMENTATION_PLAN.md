# Reinforcement-learning implementation plan

## Architecture

Train from random initialization on the secondary laptop. CARLA, simulation
ticks, reset/step execution, vehicle ownership and final safety enforcement
belong to the primary laptop. The completed policy must run with full graphics,
shadows, dense scenery and animated wind-blown foliage.

## Implemented

- Independent localhost client and host gateway, with versioned bounded JSON,
  ephemeral-secret authentication, per-session ordering and single-use command
  tokens whose expiration uses the host's monotonic clock.
- Reset/step contract, observations, requested/applied actions, provisional
  reward breakdowns, terminal/truncated reasons and no-progress cutoff.
- Toy-physics fixtures, malformed/late/replay/disconnect checks, and a separate
  process diagnostic that never creates or trains a model.
- Opt-in full-graphics CARLA adapter for short empty-road routes. Not traffic-ready.
- Verified TLS transport, paired public certificate/client token, exact peer
  allowlist and portable no-training diagnostics. Physical-PC tests remain pending.

## Remaining work

1. Validate and refine observations/rewards against CARLA traffic-rule scenarios,
   including junctions, stop lines, stop signs, blocked roads, legal waiting,
   pedestrians and collision-sensor timing. Calibrate rewards against exploits.
2. Add framework spaces/wrappers and deterministic evaluation specifications.
   Expand the empty-road adapter only with tests and bounded live evidence.
3. Validate routing/firewall and actual disconnect/recovery on the physical LAN.
   TLS and exact certificate matching are implemented; do not bypass them.
4. Choose and install RL dependencies after checking the secondary laptop's
   actual hardware. Implement the trainer and evaluation from scratch.
5. Test against two physical laptops. Measure latency and rendered frame rate;
   train/evaluate without confusing safety overrides with learned behavior.

## Ownership

All source, settings, datasets, checkpoints and logs for this client remain
inside this folder. Communication with the host uses a specified protocol;
it must never import host code or load files from a sibling application.
Future deployment can copy this folder to the secondary laptop.

## Model and rendering requirements

The existing imitation policy is separate from the RL trainer and will not initialize it. Training starts from random initialization. Headless mode may support development; policy demonstrations should retain full graphics.
