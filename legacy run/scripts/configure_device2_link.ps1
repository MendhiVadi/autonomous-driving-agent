param([string]$InterfaceAlias = "Ethernet", [string]$Address = "10.42.0.2")
$ErrorActionPreference = "Stop"
Write-Host "Configure Device 2 as $Address/24. Run PowerShell as Administrator."
& (Join-Path $PSScriptRoot 'configure_direct_link.ps1') -InterfaceAlias $InterfaceAlias -Address $Address
Write-Host "Device 2 wired address: $Address/24"
