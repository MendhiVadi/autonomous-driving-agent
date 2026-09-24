# Remote client

This application provides the network client for a two-computer CARLA setup. The reinforcement-learning trainer and policy inference are planned; training will start from random initialization. The client uses the Python standard library and runs independently of the other applications.

## Connection test

Python 3.11 or newer is sufficient. Run `python -I -B check_environment.py` to report Python and optional learning-library availability. It does not install packages.

With a localhost host gateway running, set the same random `SIM_GATEWAY_TOKEN` in both processes:

```powershell
python -I -B diagnose.py --steps 5
python -I -B tests/run_tests.py
```

Diagnostics hold the brake by default. `--allow-motion` enables fixed throttle. The `red_light` and `obstacle` scenarios are supported by the toy backend only. Diagnostics are limited to 200 steps.

For another computer, use the paired TLS connection described in [START_HERE.md](START_HERE.md). Public source does not include credentials.

## Interface

`RemoteEnvironment.reset()` returns `(observation, info)`. `step()` returns `(observation, reward, terminated, truncated, info)`. This interface does not yet include Gymnasium spaces or wrappers.

A lost response is not retried: the host may already have applied the action. Reconnect and reset before continuing. Plaintext connections are restricted to localhost; private-network connections verify the paired certificate.

## Layout

- `src/rl_client/`: client, transport and message validation.
- `diagnose.py`: bounded reset/step diagnostics using fixed controls.
- `probe.py`: TLS and authentication check without a reset.
- `tests/`: offline tests.
- `docs/IMPLEMENTATION_PLAN.md`: remaining trainer and evaluation work.

Checkpoints and run logs belong in this application's `checkpoints/` and `runs/` folders. The primary computer owns simulation ticks and final vehicle controls. Physical two-PC tests are still pending; see the [protocol](docs/PROTOCOL.md).
