param([int]$Port = 2000)
$ErrorActionPreference = "Stop"
New-NetFirewallRule -DisplayName "CARLA RPC $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private -ErrorAction SilentlyContinue
Write-Host "Allowed inbound CARLA TCP RPC port $Port on the Private profile."
