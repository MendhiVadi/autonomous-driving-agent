# Ethernet and transfer

## Connection snapshot: 2026-10-01

Laptop 1: `169.254.41.109/16`, adapter `Ethernet`, Realtek USB GbE, observed 100 Mbps.
Laptop 2: user-supplied `169.254.102.28`; its MAC resolved across the cable.
Laptop 2's TCP 445 test failed. An IP resolving on Ethernet does not prove SMB or
gateway connectivity. Recheck addresses after cable/adapter changes.

## Receive files on laptop 2

Open `\\169.254.41.109\Laptop2Transfer` in File Explorer on laptop 2.
The sender share is encrypted and read-only for `MENDHI_VADI\medha`. If prompted,
the human enters laptop 1's Windows account password, not its Windows Hello PIN.
Do not store credentials in notes or logs. Laptop 2 does not need inbound SMB to
pull files from laptop 1.

- `laptop-2.zip`: client package, including this vault snapshot and private client pairing files.
- `obsidian-vault.zip`: standalone knowledge snapshot, without pairing credentials.
- `TRANSFER_README.md`: current copy and verification instructions.

Copy ZIPs locally, check the SHA-256 files supplied beside them, and extract into
a new destination. Open the extracted `vault` folder as a vault in Obsidian.
Do not run a model directly from the network share.

From the extracted laptop 2 application folder:
```powershell
python -I -B verify_bundle.py
python -I -B check_environment.py
python -I -B tests/run_tests.py
powershell.exe -NoProfile -File scripts/network_info.ps1
```

## Connect the gateway

Laptop 1's trusted Ethernet profile must be Private for its gateway firewall script.
In Administrator PowerShell inside laptop 1, preview and then apply:
```powershell
.\scripts\allow_peer.ps1 -PrimaryAddress 169.254.41.109 -SecondaryAddress 169.254.102.28 -InterfaceAlias Ethernet -WhatIf
.\scripts\allow_peer.ps1 -PrimaryAddress 169.254.41.109 -SecondaryAddress 169.254.102.28 -InterfaceAlias Ethernet
```
If the rule already exists, inspect it instead of replacing it blindly.
Start the host from laptop 1:
```powershell
.\run_network.cmd 169.254.41.109 169.254.102.28
```
After initialization, run on laptop 2:
```powershell
Test-NetConnection 169.254.41.109 -Port 8765
python -I -B probe.py 169.254.41.109
.\connect.cmd 169.254.41.109
```
Compare certificate fingerprints first. The diagnostic performs five brake-held
steps and starts no training. Server private keys stay on laptop 1.

## Stable addresses later

Proposed direct-link addresses are `10.42.0.1/24` and `10.42.0.2/24`, no Ethernet
gateway or DNS. First check subnet conflicts. Coordinate changes to both adapters,
SMB firewall binding, gateway rule, peer allowance and launch commands together.
The current addresses and rules remain the connection snapshot until that migration.

