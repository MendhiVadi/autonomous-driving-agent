# Read-only inventory. Does not alter adapters, routes, firewall, or models.
$ErrorActionPreference = 'Stop'
Get-NetIPConfiguration | Select-Object InterfaceAlias,InterfaceIndex,IPv4Address,IPv4DefaultGateway
Get-NetConnectionProfile | Select-Object InterfaceAlias,NetworkCategory
python --version
$projectRoot = Split-Path -Parent $PSScriptRoot
$pairing = Join-Path $projectRoot 'credentials/pairing.json'
if (Test-Path -LiteralPath $pairing) {
    Get-Content -LiteralPath $pairing -Raw | ConvertFrom-Json | Select-Object server_name,certificate_sha256,port
} else { Write-Warning 'Pairing files are not installed in this application.' }
