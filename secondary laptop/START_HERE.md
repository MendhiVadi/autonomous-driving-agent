# Connect the second PC

Python 3.11 or newer with the standard `ssl` module is sufficient to run the
client. CARLA runs on the primary PC. Public source excludes pairing credentials;
create a private transfer ZIP using the repository's pairing instructions.

## First copy

1. Extract the supplied ZIP into a normal local folder on this PC.
2. Keep the ZIP and `credentials` folder private: they contain the client
   access token. The simulator's private certificate key is **not** included.
3. Open a terminal in this folder and run:

```powershell
python -I -B verify_bundle.py
python -I -B check_environment.py
python -I -B tests/run_tests.py
powershell.exe -NoProfile -File scripts/network_info.ps1
```

The manifest detects accidental transfer corruption; it is not a digital
signature. Verification requires the client source and pairing files, checks
their hashes, and rejects unlisted source or credentials. Generated logs,
environments and run outputs are excluded. Transfer the ZIP through a trusted USB/direct link, not a public
download link. Compare the certificate SHA-256 printed by `network_info.ps1`
with the primary PC's value before using the connection.

## Connect

Use Ethernet or the same trusted private router. The two PCs must have
reachable private IPv4 addresses; check both PCs' current addresses before connecting. The primary PC's connection checklist covers its exact peer-only
firewall rule. Nothing here alters network settings automatically.

After the primary PC starts its network launcher:

```powershell
python -I -B probe.py PRIMARY_IP
.\connect.cmd PRIMARY_IP
```

Replace `PRIMARY_IP` with the actual primary-PC IPv4 address (no angle brackets).
The probe verifies TLS/authentication without resetting the world. `connect.cmd`
then resets an empty-road episode and executes five brake-held steps. Neither
command starts training or loads any model. CARLA stays on the primary PC.

Only TCP 8765 is needed between PCs. Do not expose raw CARLA ports 2000–2002,
disable certificate verification, turn off the firewall, or open a router port.
If connection fails, check the IPs, exact adapter, network profile, firewall
rule, certificate fingerprint, both PC clocks, and Python availability.
Certificates expire 30 days after creation; expired or mismatched certificates
fail closed. Generate and transfer fresh pairing credentials when they expire or no longer match.

The current simulator adapter is an empty-road engineering test, not a
traffic-capable trained driver. RL training is still deliberately pending.
