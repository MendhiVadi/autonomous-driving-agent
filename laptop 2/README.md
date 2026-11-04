# Secondary laptop

Read [the project knowledge index](vault/00-Index.md) for this package's Obsidian
vault. Open the local `vault` folder as a vault in Obsidian. It is a snapshot from
laptop 1; preserve local additions when refreshing it. AI agents follow AGENTS.md.

This folder owns the future reinforcement-learning trainer, policy inference
and navigation decisions. Training starts from scratch.

No pretrained policy, old training data, or imitation-learning runtime is
loaded by this workspace. It has no import or filesystem dependency on either
sibling application. Required support code will be maintained as local copies.

Run `python -B check_environment.py` on the laptop 2 to inventory
Python and available learning libraries. This command does not install packages,
load weights, start training, or connect to the simulator.

## Current layout

- `src/rl_client/`: independent, standard-library network client and wire format.
- `docs/IMPLEMENTATION_PLAN.md`: work required before RL training can start.
- `check_environment.py`: read-only local dependency check.
- `diagnose.py`: bounded fixed-control reset/step check; never trains or loads a model.
- `tests/run_tests.py`: independent offline client tests.

Future checkpoints and run logs belong in local `checkpoints/` and `runs/`
folders. No automatic search of other applications is permitted.

The laptop 1 owns the environment and final vehicle commands. The
secondary sends bounded decisions over the paired TLS/private-IP connection
or the optional plaintext localhost rehearsal.
The final driving experience renders full scenery and wind-blown foliage on
the laptop 1. Remote training/inference is not operational yet.

## Try the connection without training

Set the same newly generated random `SIM_GATEWAY_TOKEN` (at least 32 ASCII
characters) in each process environment. With the host gateway running:

```powershell
python -I -B diagnose.py --steps 5
python -I -B tests/run_tests.py
```

The default diagnostic keeps the car braked. `--allow-motion` explicitly opts
into fixed throttle, **not** learned driving. `--scenario red_light` and
`--scenario obstacle` are toy-backend tests only. Maximum diagnostic length is
200 steps. No dependencies are installed and no checkpoints are created.

`RemoteEnvironment.reset()` returns `(observation, info)`; `step()` returns
`(observation, reward, terminated, truncated, info)`. This is a framework-neutral
interface, not yet a registered Gymnasium environment with spaces/wrappers.
No automatic retry occurs after a lost response: reconnect and reset because
the previous action may already have reached the simulator.

Non-loopback addresses require certificate-verified TLS. Plaintext development
connections are limited to localhost. See [connection instructions](START_HERE.md).
See [protocol](docs/PROTOCOL.md). Copying this folder to another PC requires no
source files from another application. Physical two-PC tests are still pending.
