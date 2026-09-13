param(
    [string]$CarlaRoot = "C:\Users\medha\Documents\CARLA\CARLA_0.9.16",
    [string]$Archive = "C:\Users\medha\Documents\CARLA\AdditionalMaps_0.9.16.zip",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($CarlaRoot)
$zip = [IO.Path]::GetFullPath($Archive)
$content = Join-Path $root "CarlaUE4\Content"

if (!(Test-Path -LiteralPath $zip)) { throw "Archive not found: $zip" }
if (!(Test-Path -LiteralPath $content)) { throw "Not a CARLA 0.9.16 root: $root" }

$entries = tar -tf $zip | Where-Object { $_ -like "CarlaUE4/Content/*" }
if (!$entries) { throw "The archive does not contain CarlaUE4/Content assets." }

$mapNames = $entries | Select-String -Pattern "Town(11|12|13|14|15)" | ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
Write-Host "Archive: $zip"
Write-Host "Target:  $content"
Write-Host "Maps detected: $($mapNames -join ', ')"

if (!$Force) {
    Write-Host "Dry run only. Re-run with -Force to extract into the CARLA installation."
    exit 0
}

if (Get-Process -Name CarlaUE4,CarlaUE4-Win64-Shipping -ErrorAction SilentlyContinue) {
    throw "Close CARLA before installing map assets."
}

# The archive paths are already relative to the CARLA installation root.
tar -xf $zip -C $root
Write-Host "Additional map assets installed. Launch CARLA and load Town11/Town12/etc. from a client."
