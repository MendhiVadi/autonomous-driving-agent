param(
    [string]$CarlaRoot = '',
    [string]$Archive = '',
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
$CarlaRoot = Resolve-CarlaRoot $CarlaRoot
if (-not $Archive) { $Archive = Join-Path (Split-Path -Parent $CarlaRoot) 'AdditionalMaps_0.9.16.zip' }
if (-not (Test-Path -LiteralPath (Join-Path $CarlaRoot 'CarlaUE4\Content'))) { throw 'Invalid CARLA installation.' }
if ($Force -and (Get-Process -Name CarlaUE4,CarlaUE4-Win64-Shipping -ErrorAction SilentlyContinue)) { throw 'Close CARLA before installing maps.' }
$arguments = @((Join-Path (Split-Path -Parent $PSScriptRoot) 'app\runtime\archive.py'), $Archive, $CarlaRoot)
if ($Force) { $arguments += '--extract' }
& (Join-Path $CarlaRoot 'carla_env\Scripts\python.exe') @arguments
if ($LASTEXITCODE -ne 0) { throw 'Map validation or extraction failed.' }
