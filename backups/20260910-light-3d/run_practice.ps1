param(
    [string]$CarlaRoot = 'C:\Users\medha\Documents\CARLA\CARLA_0.9.16',
    [ValidateSet('dx11', 'dx12', 'vulkan')][string]$RenderApi = 'dx11',
    [ValidateSet('map', 'parking', 'safe')][string]$CameraProfile = 'map',
    [double]$MaxRuntimeSeconds = 0
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $CarlaRoot 'carla_env\Scripts\python.exe'
$server = Join-Path $CarlaRoot 'CarlaUE4.exe'
$cockpit = Join-Path $CarlaRoot 'spawn_car.py'
$logDir = Join-Path $appRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runName = 'practice-' + (Get-Date -Format 'yyyyMMdd-HHmmss')

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
        & $python -c "import sys; sys.path.insert(0,sys.argv[1]); from stack_supervisor import carla_rpc_probe; sys.exit(0 if carla_rpc_probe('127.0.0.1',2000) else 1)" $appRoot 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

$activeDriver = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python' -and $_.CommandLine -match '(spawn_car|neural_drive_agent|stack_supervisor)\.py'
}
if ($activeDriver) {
    throw 'Another cockpit or supervised driver is active. Close it or run stop_stack.cmd first.'
}
& $python (Join-Path $appRoot 'health_guard.py')
if ($LASTEXITCODE -ne 0) { throw 'The thermal/hardware cooldown is still active.' }

if (Get-CarlaProcesses) {
    Write-Host 'Checking the existing CARLA server...'
    if (-not (Test-CarlaReady)) {
        Write-Host 'Removing an unresponsive CARLA instance before practice mode.'
        Stop-CarlaProcesses
    }
}

$ownedServer = -not [bool](Get-CarlaProcesses)
try {
if ($ownedServer) {
    Write-Host 'Starting one low-load CARLA server...'
    Start-Process -FilePath $server `
        -ArgumentList @('-RenderOffScreen', "-$RenderApi", '-quality-level=Low', '-nosound',
                        '-NoVSync', '-NoBloom', '-NoMotionBlur', '-ResX=320',
                        '-ResY=180', '-fps=20', '-unattended', '-carla-rpc-port=2000') `
        -WorkingDirectory $CarlaRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "$runName-server.log") `
        -RedirectStandardError (Join-Path $logDir "$runName-server.error.log")
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
    throw "CARLA did not become ready within 180 seconds. See $logDir and the latest Unreal crash report."
}

$env:PYTHONPATH = "$appRoot;$env:PYTHONPATH"
Write-Host "CARLA is ready. Opening $CameraProfile practice mode."
    # Keep Python stderr in the log without promoting each native stderr line
    # into a terminating PowerShell error; propagate the real process exit code.
    $ErrorActionPreference = 'Continue'
    & $python -u $cockpit --map Town05 --camera-profile $CameraProfile `
        --window-width 1280 --window-height 720 --target-fps 20 `
        --camera-fps 4 --mirror-camera-fps 2 --input-latch-ms 35 `
        --route-speed-kmh 30 --graphics-throttle-start-kmh 32 `
        --graphics-speed-cap-kmh 48 --visual-austerity-start-kmh 32 `
        --visual-austerity-resume-kmh 26 --runtime-rpc-timeout 2 `
        --max-runtime-seconds $MaxRuntimeSeconds `
        --screenshot-path (Join-Path $logDir "practice-$CameraProfile.png") 2>&1 |
        Tee-Object -FilePath (Join-Path $logDir "$runName-cockpit.log")
    $ErrorActionPreference = 'Stop'
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
