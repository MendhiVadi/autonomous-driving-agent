param([string]$InterfaceAlias = "Ethernet", [string]$Address = "10.42.0.2")
$ErrorActionPreference = "Stop"
Write-Host "Configure Device 2 as $Address/24. Run PowerShell as Administrator."
Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {$_.PrefixOrigin -eq "Manual"} | Remove-NetIPAddress -Confirm:$false
New-NetIPAddress -InterfaceAlias $InterfaceAlias -IPAddress $Address -PrefixLength 24
Write-Host "Device 2 wired address: $Address/24"
