param([string]$InterfaceAlias = "Ethernet", [string]$Address = "10.42.0.1")
$ErrorActionPreference = "Stop"
Write-Host "Configuring Device 1 as $Address/24 on its wired adapter. Run PowerShell as Administrator."
Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {$_.PrefixOrigin -eq "Manual"} | Remove-NetIPAddress -Confirm:$false
New-NetIPAddress -InterfaceAlias $InterfaceAlias -IPAddress $Address -PrefixLength 24
Write-Host "Device 1 wired address: $Address/24"
