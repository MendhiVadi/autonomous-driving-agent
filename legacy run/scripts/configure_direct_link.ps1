param(
    [Parameter(Mandatory=$true)][string]$InterfaceAlias,
    [Parameter(Mandatory=$true)][string]$Address
)
$ErrorActionPreference = 'Stop'
$parsedAddress = [Net.IPAddress]::Parse($Address)
if ($parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $Address -notmatch '^10\.42\.0\.(1|2)$') {
    throw 'The direct link expects 10.42.0.1 or 10.42.0.2, with a /24 prefix.'
}
$adapter = Get-NetAdapter -Name $InterfaceAlias
$existing = @(Get-NetIPAddress -InterfaceIndex $adapter.InterfaceIndex -AddressFamily IPv4)
$matching = @($existing | Where-Object { $_.IPAddress -eq $Address })
if ($matching.Count) {
    if ($matching[0].PrefixLength -ne 24) { throw 'The requested address exists with a conflicting prefix.' }
    Write-Host 'The requested direct-link address is already configured.'
    return
}
if ($existing | Where-Object { $_.PrefixOrigin -eq 'Manual' -and $_.IPAddress -notlike '169.254.*' }) {
    throw 'This adapter already has a static address. Review its configuration; no addresses were removed.'
}
if (Get-NetRoute -InterfaceIndex $adapter.InterfaceIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue) {
    throw 'This adapter carries a default route. Use the dedicated direct-link adapter.'
}
New-NetIPAddress -InterfaceIndex $adapter.InterfaceIndex -IPAddress $Address -PrefixLength 24 | Out-Null
