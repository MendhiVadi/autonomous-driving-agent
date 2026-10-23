param(
    [ValidateRange(1,65535)][int]$Port = 2000,
    [string]$LocalAddress = '10.42.0.1',
    [string]$Device2Address = '10.42.0.2'
)
$ErrorActionPreference = 'Stop'
[void][Net.IPAddress]::Parse($LocalAddress)
[void][Net.IPAddress]::Parse($Device2Address)
$ruleName = "AutonomousDrivingAgent-RPC-$Port"
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Private
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $LocalAddress -RemoteAddress $Device2Address
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName "Autonomous Driving RPC $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -LocalAddress $LocalAddress -RemoteAddress $Device2Address -Action Allow -Profile Private | Out-Null
}
Write-Host "Allowed CARLA RPC $LocalAddress`:$Port from $Device2Address on the Private profile."
