# Connection-day checklist â€” prepared 2026-09-24

No training is started by any command on this page. Only the gateway connects
the two PCs; CARLA, graphics, world ticks and final controls remain on this PC.

## Before attaching the other PC

- From the repository root, create credentials with
  `python -I -B "primary laptop/prepare_pairing.py"`, then build the client ZIP
  with `python -I -B build_handoff.py`. These files are excluded from Git.
  Never copy `credentials/server-key.pem` to another PC.
- Use the latest ZIP in the root `handoff` folder. It contains an independent
  client, its public server certificate and access token, but no server key,
  model, dataset, Python environment or simulator files.
- Treat that ZIP as private. Transfer it by trusted USB/direct link. Read the
  included `START_HERE.md` on the second PC. No RL libraries are required yet.
- The localhost encrypted rehearsal is `python -I -B check_local_link.py --tls`
  from the workspace root. It uses toy physics and does not launch CARLA.

## Once both PCs are connected

1. Use a direct Ethernet link or the same trusted private router. Run
   `scripts/network_info.ps1` in each application to read actual addresses and
   adapter names. Do not assume the previous Wi-Fi address is still current.
   Compare the certificate fingerprint on both PCs. Do not change IP settings
   blindly; an unconfigured direct cable may have link-local 169.254 addresses.
2. If the selected link is marked Public, establish that it is your trusted
   private link before changing its Windows network profile. The scripts never
   change adapter addresses, routes, DNS, network profiles or firewall policy
   automatically.
3. In an elevated PowerShell terminal on this PC, preview the scoped rule:

```powershell
.\scripts\allow_peer.ps1 -PrimaryAddress PRIMARY_IP -SecondaryAddress SECONDARY_IP -InterfaceAlias "ADAPTER_NAME" -WhatIf
```

Replace those three placeholders with the actual values. After checking the
preview, rerun without `-WhatIf`. This adds only inbound TCP 8765 for the CARLA
Python executable, exact adapter/local address and exact secondary address,
on the Private profile. Existing rules are never replaced or deleted. If a
same-named rule already exists, inspect it rather than broadening permissions.


4. Start this PC's full-graphics gateway:

```powershell
.\run_network.cmd PRIMARY_IP SECONDARY_IP
```

The connection-day check uses Town02_Opt. Keep that default for the first
physical connection. Town13 is an optional **experimental diagnostic**, not the
connection-day baseline; its gateway map load/tile warm-up still times out in
some runs. To investigate it separately, use the explicit launcher:

```powershell
.\run_gateway.cmd -Tls -GatewayBind PRIMARY_IP -PeerAddress SECONDARY_IP -Map Town13
```

Town13 passed one bounded full-graphics manual stationary test, but subsequent
network-controlled tests did not complete initialization reliably. That manual
result does not establish gateway readiness. Warm-up is deliberately brake-held;
do not launch a second client during initialization or increase timeouts as a
substitute for a successful test. See [map evidence](MAPS.md).

5. On the other PC run the commands in `START_HERE.md`: verify the bundle,
   probe TLS, then execute five brake-held steps. No second client should be
   connected simultaneously. Stop this host with Ctrl+C in its terminal.

## What still needs the other PC

Actual firewall/routing validation, cable pull and reconnection, latency and
render-rate measurements with both machines, hardware inventory and choice
of learning dependencies. No bandwidth, latency or GPU-training capability is
claimed for a device that has not yet been attached. Keep model training off.

Traffic perception/evaluation, reward calibration, learning-framework wrappers,
trainer/checkpointing and real driving evaluation are separate later work.
