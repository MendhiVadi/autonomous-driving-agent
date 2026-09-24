# Create the host environment using the bundled CARLA API wheel.
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config/runtime.json') -Raw | ConvertFrom-Json
$carlaRoot = if ($env:CARLA_ROOT) { $env:CARLA_ROOT } else { [Environment]::ExpandEnvironmentVariables($config.carla_root) }
$wheel = Join-Path $carlaRoot 'PythonAPI/carla/dist/carla-0.9.16-cp312-cp312-win_amd64.whl'
if (-not (Test-Path -LiteralPath $wheel -PathType Leaf)) { throw 'The official bundled Python 3.12 CARLA wheel is missing.' }
& $Python -I -B -c "import sys; assert sys.version_info[:2]==(3,12), 'Use Python 3.12 for the bundled CARLA wheel'"
if ($LASTEXITCODE -ne 0) { throw 'Host runtime setup requires Python 3.12.' }
$environment = Join-Path $projectRoot '.venv'
$hostPython = Join-Path $environment 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $environment)) {
    & $Python -I -B -m venv $environment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated host environment.' }
} elseif (-not (Test-Path -LiteralPath $hostPython -PathType Leaf)) {
    throw 'Existing incomplete environment preserved; inspect it before continuing.'
}
& $hostPython -I -B -m pip install --no-index --no-deps --disable-pip-version-check $wheel
if ($LASTEXITCODE -ne 0) { throw 'Bundled CARLA wheel installation failed.' }
& $hostPython -I -B -c "import carla,sys; print('Isolated host Python:',sys.version.split()[0]); print('CARLA client:',carla.Client('127.0.0.1',2000).get_client_version())"
if ($LASTEXITCODE -ne 0) { throw 'CARLA API import check failed.' }
