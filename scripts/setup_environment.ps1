<#
.SYNOPSIS
Create the project's Python environment inside the CARLA installation.

.DESCRIPTION
Creates <CARLA_ROOT>\carla_env, installs the CARLA client wheel that ships in
<CARLA_ROOT>\PythonAPI\carla\dist for a matching Python version, then installs
requirements\carla_env.txt (pygame, numpy, networkx, shapely). Run it once after
installing CARLA 0.9.16, and again after reinstalling Windows. The launchers
offer to run it automatically when the environment is missing.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\setup_environment.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup_environment.ps1 -Python C:\Python312\python.exe
#>
param(
    [string]$CarlaRoot = '',
    [string]$Python = '',
    [switch]$Recreate
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$CarlaRoot = Resolve-CarlaRoot $CarlaRoot
if (-not (Test-Path -LiteralPath (Join-Path $CarlaRoot 'CarlaUE4.exe') -PathType Leaf)) {
    throw ("CARLA 0.9.16 was not found at '$CarlaRoot'. Extract the CARLA_0.9.16 Windows package there, " +
           "set the CARLA_ROOT environment variable, or edit config\runtime.json.")
}
$dist = Join-Path $CarlaRoot 'PythonAPI\carla\dist'
$wheels = @(Get-ChildItem -LiteralPath $dist -Filter 'carla-*-win_amd64.whl' -ErrorAction SilentlyContinue)
if (-not $wheels.Count) {
    throw "No CARLA client wheel was found in $dist. The Windows package ships carla-0.9.16-cp3XX-cp3XX-win_amd64.whl files there."
}

function Invoke-Quietly([scriptblock]$Body) {
    # Probing interpreters writes to stderr when a version is absent; that must not abort the script.
    $previous = $ErrorActionPreference
    try { $ErrorActionPreference = 'Continue'; return (& $Body) } catch { return $null } finally { $ErrorActionPreference = $previous }
}
function Get-InterpreterVersion([string]$Executable) {
    $version = Invoke-Quietly { & $Executable -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null }
    if ($LASTEXITCODE -eq 0 -and $version) { return "$version".Trim() }
    return $null
}

$wheelByVersion = @{}
foreach ($wheel in $wheels) {
    if ($wheel.Name -match '-cp(\d)(\d+)-') { $wheelByVersion["$($Matches[1]).$($Matches[2])"] = $wheel.FullName }
}
$supported = @($wheelByVersion.Keys | Sort-Object { [version]$_ } -Descending)

$chosen = $null
$chosenVersion = $null
if ($Python) {
    $chosenVersion = Get-InterpreterVersion $Python
    if (-not $chosenVersion) { throw "Could not run the Python interpreter '$Python'." }
    if (-not $wheelByVersion.ContainsKey($chosenVersion)) {
        throw "Python $chosenVersion has no bundled CARLA wheel. Bundled versions: $($supported -join ', ')."
    }
    $chosen = $Python
} else {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    foreach ($version in $supported) {
        if (-not $launcher) { break }
        $candidate = Invoke-Quietly { & py "-$version" -c "import sys; print(sys.executable)" 2>$null }
        if ($LASTEXITCODE -eq 0 -and $candidate) { $chosen = "$candidate".Trim(); $chosenVersion = $version; break }
    }
    if (-not $chosen) {
        foreach ($name in @('python', 'python3')) {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if (-not $command) { continue }
            $version = Get-InterpreterVersion $command.Source
            if ($version -and $wheelByVersion.ContainsKey($version)) { $chosen = $command.Source; $chosenVersion = $version; break }
        }
    }
    if (-not $chosen) {
        throw ("No installed Python matches a bundled CARLA wheel. Install 64-bit Python $($supported[0]) from python.org " +
               "(tick 'Add to PATH'), or pass -Python <path to python.exe>. Bundled wheel versions: $($supported -join ', ').")
    }
}

$wheel = $wheelByVersion[$chosenVersion]
$venv = Join-Path $CarlaRoot 'carla_env'
$venvPython = Join-Path $venv 'Scripts\python.exe'
Write-Host "CARLA:  $CarlaRoot"
Write-Host "Python: $chosen (version $chosenVersion)"
Write-Host "Wheel:  $wheel"
Write-Host "Target: $venv"
if ($Recreate -and (Test-Path -LiteralPath $venv)) { Remove-Item -LiteralPath $venv -Recurse -Force }
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $venv) { throw "An incomplete environment exists at $venv. Re-run with -Recreate to replace it." }
    & $chosen -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $venvPython -m pip install --disable-pip-version-check $wheel
if ($LASTEXITCODE -ne 0) { throw 'CARLA wheel installation failed.' }
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements\carla_env.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython -c "import carla, pygame, numpy, networkx, shapely; print('carla client', carla.Client('127.0.0.1', 2000).get_client_version(), '| pygame', pygame.version.ver, '| numpy', numpy.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Import check failed.' }
Write-Host 'Environment ready. Run run_car.cmd, run_neural.cmd or run_large_map_neural.cmd.'
