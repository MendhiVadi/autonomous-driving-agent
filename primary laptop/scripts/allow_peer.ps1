[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$PrimaryAddress,
    [Parameter(Mandatory)][string]$SecondaryAddress,
    [Parameter(Mandatory)][string]$InterfaceAlias
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config/runtime.json') -Raw | ConvertFrom-Json
$carlaRoot = if ($env:CARLA_ROOT) { $env:CARLA_ROOT } else { [Environment]::ExpandEnvironmentVariables($config.carla_root) }
$localPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
$python = if (Test-Path -LiteralPath $localPython -PathType Leaf) { $localPython } else { Join-Path $carlaRoot 'carla_env/Scripts/python.exe' }
& $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from sim_host.transport import local_address; a=local_address(sys.argv[2]); b=local_address(sys.argv[3]); assert a!='127.0.0.1' and b!='127.0.0.1' and a!=b" (Join-Path $projectRoot 'src') $PrimaryAddress $SecondaryAddress
if ($LASTEXITCODE -ne 0) { throw 'Use two different private IPv4 addresses.' }
if ($InterfaceAlias -match '[*?\[\]]') { throw 'Use an exact adapter name, not a wildcard.' }
$adapter = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $InterfaceAlias | Where-Object IPAddress -eq $PrimaryAddress
if (-not $adapter) { throw 'The primary address is not assigned to this adapter.' }
$profile = Get-NetConnectionProfile -InterfaceIndex $adapter.InterfaceIndex
if ($profile.NetworkCategory -ne 'Private') { throw 'Use a trusted private link. This script will not change the network profile.' }
$ruleName = 'ADA-SecureGateway-' + $SecondaryAddress.Replace('.', '-')
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    throw "A rule named $ruleName already exists. Inspect it; this script will not replace or delete it."
}
if ($PSCmdlet.ShouldProcess("$InterfaceAlias / $PrimaryAddress TCP 8765 from $SecondaryAddress", 'Add private-profile gateway firewall rule')) {
    New-NetFirewallRule -Name $ruleName -DisplayName "CARLA encrypted gateway from $SecondaryAddress" `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress $PrimaryAddress `
        -RemoteAddress $SecondaryAddress -InterfaceAlias $InterfaceAlias -Program $python `
        -Profile Private -EdgeTraversalPolicy Block | Select-Object Name,Enabled,Profile,Direction,Action
}
