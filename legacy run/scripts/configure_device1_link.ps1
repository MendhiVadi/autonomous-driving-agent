param([string]$InterfaceAlias = "Ethernet", [string]$Address = "10.42.0.1")
$ErrorActionPreference = "Stop"
Write-Host "Configuring Device 1 as $Address/24 on its wired adapter. Run PowerShell as Administrator."
& (Join-Path $PSScriptRoot 'configure_direct_link.ps1') -InterfaceAlias $InterfaceAlias -Address $Address
Write-Host "Device 1 wired address: $Address/24"
