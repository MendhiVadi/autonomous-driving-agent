# Autonomous driving agent

A Windows CARLA project with a manual driving host, an experimental two-computer control link, and a separate imitation-learning runtime.

| Application | Role |
| --- | --- |
| [Primary laptop](primary%20laptop/README.md) | CARLA, graphics, physics, vehicle controls and the reset/step gateway |
| [Secondary laptop](secondary%20laptop/README.md) | Remote client, connection diagnostics and the planned RL trainer |
| [Legacy run](legacy%20run/README.md) | Manual driving, map cockpit, imitation-policy inference and data collection |

Each application owns its source and configuration. The primary computer advances the simulation; the secondary computer sends bounded commands over an authenticated connection. The RL trainer is still under development. The legacy policy uses road and vehicle state, rather than camera images.

## Quick start

Install CARLA 0.9.16 for Windows and Python 3.12. Set `CARLA_ROOT` to the extracted CARLA directory, or edit the primary application's `config/runtime.json`.

From PowerShell in this repository:

```powershell
$env:CARLA_ROOT = 'C:\CARLA\CARLA_0.9.16'
powershell.exe -NoProfile -File 'primary laptop/scripts/setup_host_runtime.ps1'
& '.\primary laptop\run_manual.cmd' -Check
& '.\primary laptop\run_manual.cmd'
```

The setup script installs CARLA's bundled Python 3.12 API wheel into the host's own environment. Manual mode uses Epic graphics, a native 1280 x 720 viewport and a 30 FPS cap. Click the CARLA window, drive with WASD or the arrow keys, and press Esc to exit. Only one managed CARLA session can run at a time.

## Test the control link

The localhost rehearsal uses toy physics and requires no CARLA installation:

```powershell
python -I -B check_local_link.py
```

For TLS, install OpenSSL or use the copy included with Git for Windows, then create pairing credentials and a private client package:

```powershell
python -I -B 'primary laptop/prepare_pairing.py'
python -I -B build_handoff.py
python -I -B check_local_link.py --tls
```

The generated ZIP contains a client access token. Transfer it privately to the second computer. Credentials and transfer packages are excluded from Git. Follow the [two-PC setup guide](primary%20laptop/docs/CONNECT_SECOND_PC.md) before opening the network gateway.

## Tests

```powershell
python -I -B verify_layout.py
python -I -B 'primary laptop/tests/run_tests.py'
python -I -B 'secondary laptop/tests/run_tests.py'
& '.\legacy run\verify.cmd'
```

The host TLS tests use OpenSSL. The legacy tests also require the dependencies described in its README. The latest maintenance checks passed 81 host, 23 client and 179 legacy tests. See [validation notes](primary%20laptop/docs/VALIDATION.md).

## Current limits

Town02_Opt is the default map. Town13 passed a short stationary manual check, but gateway initialization remains intermittent. Physical two-PC latency, disconnect recovery, traffic scenarios and sustained driving still need validation.

The CARLA gateway currently supports short empty-road routes. Its reward function and safety checks are experimental; they do not establish autonomous-driving performance. Trained weights, recordings, local logs, backups and simulator binaries are not included. Legacy neural mode requires a compatible policy supplied separately.
