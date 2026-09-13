param(
    [string]$CarlaRoot = 'C:\Users\medha\Documents\CARLA\CARLA_0.9.16'
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $CarlaRoot 'carla_env\Scripts\python.exe'
$server = Join-Path $CarlaRoot 'CarlaUE4.exe'
$cockpit = Join-Path $CarlaRoot 'spawn_car.py'

foreach ($required in @($python, $server, $cockpit)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required CARLA file is missing: $required"
    }
}

function Get-CarlaProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -in @('CarlaUE4.exe', 'CarlaUE4-Win64-Shipping.exe')
    })
}

function Stop-CarlaProcesses {
    foreach ($process in Get-CarlaProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Test-CarlaReady {
    # A connection timeout is normal while UE4 is still loading.  With the
    # script-wide Stop policy, PowerShell otherwise promotes Python's expected
    # stderr into a terminating NativeCommandError and aborts the launcher.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -c "import carla; c=carla.Client('127.0.0.1',2000); c.set_timeout(3); c.get_server_version(); c.get_world()" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

if (Get-CarlaProcesses) {
    Write-Host 'Checking the existing CARLA server...'
    if (-not (Test-CarlaReady)) {
        Write-Host 'Removing an unresponsive CARLA instance before practice mode.'
        Stop-CarlaProcesses
    }
}

$ownedServer = -not [bool](Get-CarlaProcesses)
if ($ownedServer) {
    Write-Host 'Starting one low-load CARLA server...'
    Start-Process -FilePath $server `
        -ArgumentList @('-RenderOffScreen', '-dx11', '-quality-level=Low', '-nosound',
                        '-NoVSync', '-NoBloom', '-NoMotionBlur', '-ResX=160',
                        '-ResY=90', '-fps=10', '-carla-rpc-port=2000') `
        -WorkingDirectory $CarlaRoot -WindowStyle Hidden
}

Write-Host 'Waiting for the CARLA world to finish loading...'
$deadline = (Get-Date).AddSeconds(180)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if (-not (Get-CarlaProcesses)) {
        throw 'CARLA exited while the world was loading. Check the latest crash report.'
    }
    if (Test-CarlaReady) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 3
}
if (-not $ready) {
    if ($ownedServer) { Stop-CarlaProcesses }
    throw 'CARLA did not become ready within 180 seconds. After a UE4 GPU/fatal crash, restart Windows before trying again; the Intel graphics context does not reliably recover in-place.'
}

$env:PYTHONPATH = "$appRoot;$env:PYTHONPATH"
Write-Host 'CARLA is ready. Opening four-camera practice mode.'
try {
    & $python -u $cockpit --map Town05 --camera-profile parking `
        --window-width 1280 --window-height 720 --target-fps 20 `
        --camera-fps 4 --mirror-camera-fps 2 --input-latch-ms 35 `
        --route-speed-kmh 30 --graphics-throttle-start-kmh 32 `
        --graphics-speed-cap-kmh 48 --visual-austerity-start-kmh 32 `
        --visual-austerity-resume-kmh 26 --runtime-rpc-timeout 2 `
        --screenshot-path (Join-Path $appRoot 'logs\practice-four-cameras.png')
    if ($LASTEXITCODE -ne 0) {
        throw "The cockpit exited with code $LASTEXITCODE."
    }
}
finally {
    if ($ownedServer) {
        Write-Host 'Stopping the practice CARLA server cleanly.'
        Stop-CarlaProcesses
    }
}
