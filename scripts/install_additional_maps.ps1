param(
    [string]$CarlaRoot = "C:\Users\medha\Documents\CARLA\CARLA_0.9.16",
    [string]$Archive = "C:\Users\medha\Documents\CARLA\AdditionalMaps_0.9.16.zip",
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $CarlaRoot 'CarlaUE4\Content'))) { throw 'Invalid CARLA installation.' }
if ($Force -and (Get-Process -Name CarlaUE4,CarlaUE4-Win64-Shipping -ErrorAction SilentlyContinue)) { throw 'Close CARLA before installing maps.' }
$arguments = @((Join-Path (Split-Path -Parent $PSScriptRoot) 'app\safe_archive.py'), $Archive, $CarlaRoot)
if ($Force) { $arguments += '--extract' }
& (Join-Path $CarlaRoot 'carla_env\Scripts\python.exe') @arguments
if ($LASTEXITCODE -ne 0) { throw 'Map validation or extraction failed.' }
