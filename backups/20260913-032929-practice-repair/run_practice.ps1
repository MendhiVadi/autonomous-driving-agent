param(
    [string]$CarlaRoot = 'C:\Users\medha\Documents\CARLA\CARLA_0.9.16',
    [ValidateSet('dx11', 'dx12', 'vulkan')][string]$RenderApi = 'dx11',
    [ValidateSet('map', 'parking', 'safe')][string]$CameraProfile = 'map',
    [double]$MaxRuntimeSeconds = 0,
    [string]$Map = 'Town02_Opt',
    [string]$RoutePolicy = '',
    [switch]$LowScenery,
    [ValidateSet('practice', 'presentation', 'training', 'expert')][string]$Mode = 'practice',
    [int]$Episodes = 12,
    [int]$MaxTicks = 2400,
    [string]$OutputDir = 'episodes/expert'
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $CarlaRoot 'carla_env\Scripts\python.exe'
$server = Join-Path $CarlaRoot 'CarlaUE4.exe'
$cockpit = Join-Path $CarlaRoot 'spawn_car.py'
$logDir = Join-Path $appRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runName = 'practice-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$routeArguments = @()
if ($Mode -eq 'practice') {
    if (-not $RoutePolicy) {
        $RoutePolicy = Join-Path $appRoot 'nn_policy_colab.json'
        if (-not (Test-Path -LiteralPath $RoutePolicy)) {
            $RoutePolicy = Join-Path $appRoot 'exports\preliminary-network-20260910-150651\nn_policy_preliminary.json'
        }
    }
    if (-not (Test-Path -LiteralPath $RoutePolicy)) {
        throw "Neural policy is missing: $RoutePolicy"
    }
    $RoutePolicy = (Resolve-Path -LiteralPath $RoutePolicy).Path
    $routeArguments = @('--route-policy', $RoutePolicy, '--preload-route-policy')
}
if ($LowScenery) {
    $Map = 'Town02_Opt'
    $CameraProfile = 'safe'
}
if ($Mode -eq 'presentation') {
    if ($LowScenery) { throw 'Presentation cannot use the low-scenery preset.' }
    $Map = 'Town04_Opt'
    $CameraProfile = 'safe'
}
if ($Mode -in @('training', 'expert')) {
    $Map = 'Town02_Opt'
    $CameraProfile = 'map'
    $LowScenery = $true
}

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
    $_.Name -match '^python' -and $_.CommandLine -match '(spawn_car|neural_drive_agent|stack_supervisor|collect_expert_data)\.py'
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
    $quality = if ($Mode -eq 'presentation') { 'Epic' } else { 'Low' }
    $serverArguments = @('-RenderOffScreen', "-$RenderApi", "-quality-level=$quality", '-nosound',
                        '-NoVSync', '-NoBloom', '-NoMotionBlur', '-ResX=320',
                        '-ResY=180', '-fps=20', '-unattended', '-carla-rpc-port=2000')
    if ($LowScenery) {
        $serverArguments += '-ExecCmds="t.MaxFPS 20,r.ViewDistanceScale 0.4,r.ShadowQuality 0,r.SSR.Quality 0,r.BloomQuality 0,r.MotionBlurQuality 0,r.VolumetricFog 0,r.DetailMode 0,foliage.DensityScale 0,grass.DensityScale 0,foliage.LODDistanceScale 0.5"'
    }
    elseif ($Mode -eq 'presentation') {
        $serverArguments += '-ExecCmds="t.MaxFPS 20,sg.ShadowQuality 1,sg.PostProcessQuality 1,sg.EffectsQuality 1,sg.FoliageQuality 2,r.ViewDistanceScale 0.7,r.MotionBlurQuality 0"'
    }
    Start-Process -FilePath $server -ArgumentList $serverArguments `
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
if ($CameraProfile -eq 'map') {
    & $python -c "import sys, carla; from simulation_environment import prepare_state_world; client=carla.Client('127.0.0.1',2000); client.set_timeout(45); world=prepare_state_world(client,carla,sys.argv[1]); print('[environment] camera-free world ready: '+world.get_map().name)" $Map
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the camera-free input environment.' }
}
Write-Host "CARLA is ready. Starting $Mode mode on $Map."
    # Keep Python stderr in the log without promoting each native stderr line
    # into a terminating PowerShell error; propagate the real process exit code.
    $ErrorActionPreference = 'Continue'
    $sceneryArguments = @()
    $frontCameraFps = 4
    if ($LowScenery) {
        $sceneryArguments = @('--low-scenery')
        $frontCameraFps = 10
    }
    if ($Mode -eq 'presentation') {
        $sceneryArguments = @('--presentation')
        $frontCameraFps = 10
    }
    if ($Mode -eq 'training') {
        $sceneryArguments += @('--human-demo', '--human-target-episodes', "$Episodes",
                               '--human-output-dir', $OutputDir, '--map-open-on-start')
    }
    if ($Mode -eq 'expert') {
        & $python -u (Join-Path $appRoot 'collect_expert_data.py') --carla-root $CarlaRoot `
            --map $Map --headless --output-dir $OutputDir --episodes $Episodes --max-ticks $MaxTicks 2>&1 |
            Tee-Object -FilePath (Join-Path $logDir "$runName-expert.log")
    }
    else {
    & $python -u $cockpit --map $Map --camera-profile $CameraProfile @sceneryArguments @routeArguments `
        --window-width 1280 --window-height 720 --target-fps 20 `
        --camera-fps $frontCameraFps --mirror-camera-fps 2 --input-latch-ms 35 `
        --route-speed-kmh 30 --graphics-throttle-start-kmh 32 `
        --graphics-speed-cap-kmh 48 --visual-austerity-start-kmh 32 `
        --visual-austerity-resume-kmh 26 --runtime-rpc-timeout 2 `
        --max-runtime-seconds $MaxRuntimeSeconds `
        --screenshot-path (Join-Path $logDir "practice-$CameraProfile.png") 2>&1 |
        Tee-Object -FilePath (Join-Path $logDir "$runName-cockpit.log")
    }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        throw "The $Mode session exited with code $LASTEXITCODE."
    }
}
finally {
    if ($ownedServer) {
        Write-Host 'Stopping the practice CARLA server cleanly.'
        Stop-CarlaProcesses
    }
}
