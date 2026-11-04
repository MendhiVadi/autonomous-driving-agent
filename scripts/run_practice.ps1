param(
    [string]$CarlaRoot = '',
    [ValidateSet('dx11', 'dx12', 'vulkan')][string]$RenderApi = 'dx11',
    [ValidateSet('map', 'parking', 'triple', 'safe')][string]$CameraProfile = 'map',
    [double]$MaxRuntimeSeconds = 0,
    [string]$Map = 'Town02_Opt',
    [string]$RoutePolicy = '',
    [switch]$NoNeuralVisual,
    [switch]$NoLaneAssist,
    [string]$RouteDestination = '',
    [string]$ScriptedKeys = '',
    [double]$DiagnosticYawOffset = 0,
    [double]$RouteAheadMeters = 0,
    [string]$DiagnosticDisplace = '',
    [int]$SpawnIndex = -1,
    [switch]$LowScenery,
    [switch]$FullGraphics,
    [switch]$RequireFreshServer,
    [switch]$OpenMap,
    [ValidateSet('practice', 'scenic', 'presentation', 'training', 'expert')][string]$Mode = 'practice',
    [int]$Episodes = 12,
    [int]$MaxTicks = 2400,
    [string]$OutputDir = 'episodes/expert'
)

if (([double]::IsNaN($MaxRuntimeSeconds) -or [double]::IsInfinity($MaxRuntimeSeconds)) -or $MaxRuntimeSeconds -lt 0) { throw 'MaxRuntimeSeconds must be finite and non-negative.' }
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'environment.ps1')
$CarlaRoot = Resolve-CarlaRoot $CarlaRoot
. (Join-Path $PSScriptRoot 'carla_startup_state.ps1')
Set-Location -LiteralPath $appRoot
$sessionMutex = [Threading.Mutex]::new($false, 'Local\AutonomousDrivingAgent.Runtime')
$leaseAcquired = $false
try {
    try { $leaseAcquired = $sessionMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $leaseAcquired = $true }
    if (-not $leaseAcquired) { throw 'Another managed CARLA session is already active.' }
$python = Join-Path $CarlaRoot 'carla_env\Scripts\python.exe'
$server = Join-Path $CarlaRoot 'CarlaUE4.exe'
$cockpit = Join-Path $appRoot 'app\spawn_car.py'
$largeMapGraphics = $FullGraphics -and $Map -in @('Town11', 'Town12', 'Town13')
$threeCameraGraphics = $FullGraphics -and $CameraProfile -eq 'triple'
$displayWidth = if ($largeMapGraphics -or $threeCameraGraphics) { 960 } else { 1280 }
$displayHeight = if ($largeMapGraphics -or $threeCameraGraphics) { 540 } else { 720 }
$displayFps = if ($largeMapGraphics -or $threeCameraGraphics) { 15 } else { 20 }
$env:CARLA_ROOT = $CarlaRoot
$logDir = Join-Path $appRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runName = $Mode + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$routeArguments = @()
if ($Mode -eq 'scenic' -and $LowScenery) { throw 'Scenic driving uses full scenery. Use run_neural.cmd for the lightweight mode.' }
if ($FullGraphics -and $LowScenery) { throw 'FullGraphics and LowScenery cannot be combined.' }
if ($FullGraphics -and $Mode -ne 'practice') { throw 'FullGraphics supports the neural practice mode only.' }
if ($Mode -eq 'practice') {
    # This launcher uses the explicit cockpit flag, not an inherited switch.
    $env:CARLA_NEURAL_VISUAL = '0'
    if (-not $RoutePolicy) {
        $RoutePolicy = Get-DefaultPolicyPath
    }
    if (-not (Test-Path -LiteralPath $RoutePolicy)) {
        throw "Neural policy is missing: $RoutePolicy"
    }
    $RoutePolicy = (Resolve-Path -LiteralPath $RoutePolicy).Path
    # Validate the contract before spending time and GPU resources on startup.
    & $python -c "import sys; sys.path.insert(0,sys.argv[1]); from neural_drive_agent import load_deployable_policy; load_deployable_policy(sys.argv[2],require_route_conditioned=True); print('[policy] validated')" (Join-Path $appRoot 'app') $RoutePolicy
    if ($LASTEXITCODE -ne 0) { throw 'Neural policy validation failed.' }
    $routeArguments = @('--route-policy', $RoutePolicy, '--preload-route-policy')
    if ($OpenMap -and -not $RouteDestination) { $routeArguments += '--map-open-on-start' }
    if (-not $NoLaneAssist) { $routeArguments += '--neural-lane-assist' }
    if (-not $NoNeuralVisual) {
        $routeArguments += '--neural-visual'
        Write-Host 'Neural activity webpage will open when the model loads. F8 reopens it.'
    }
    if ($RouteDestination) {
        $coordinates = $RouteDestination.Split(',')
        if ($coordinates.Count -ne 2) { throw 'RouteDestination must be x,y map coordinates.' }
        foreach ($coordinate in $coordinates) {
            $number = [double]::Parse($coordinate, [Globalization.CultureInfo]::InvariantCulture)
            if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) {
                throw 'RouteDestination coordinates must be finite.'
            }
        }
        $routeArguments += @('--route-destination', $coordinates[0], $coordinates[1])
    }
    if ($SpawnIndex -ge 0) { $routeArguments += @('--spawn-index', "$SpawnIndex") }
    if ($DiagnosticDisplace) {
        $displace = $DiagnosticDisplace.Split(',')
        if ($displace.Count -ne 2) { throw 'DiagnosticDisplace must be lateral_m,yaw_deg.' }
        foreach ($value in $displace) {
            $number = [double]::Parse($value, [Globalization.CultureInfo]::InvariantCulture)
            if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { throw 'DiagnosticDisplace values must be finite.' }
        }
        $routeArguments += @('--diagnostic-displace', $displace[0], $displace[1])
    }
    if ($RouteAheadMeters -gt 0) { $routeArguments += @('--route-ahead-m', $RouteAheadMeters.ToString([Globalization.CultureInfo]::InvariantCulture)) }
    if ($DiagnosticYawOffset -ne 0) { $routeArguments += @('--diagnostic-yaw-offset', $DiagnosticYawOffset.ToString([Globalization.CultureInfo]::InvariantCulture)) }
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

# RGB camera rendering hangs the server within seconds under DX11 on the Intel Arc
# 140V (3 DX11 variants and synchronous ticks all stalled; see docs/CRASH_DIAGNOSIS.md).
# DX12 ran three cameras steadily, so camera profiles default to it. An explicit
# -RenderApi always wins; the native map-profile window keeps its verified DX11 path.
if (-not $PSBoundParameters.ContainsKey('RenderApi') -and $CameraProfile -in @('triple', 'parking', 'safe')) {
    $RenderApi = 'dx12'
}

foreach ($required in @($python, $server, $cockpit)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required CARLA file is missing: $required"
    }
}

function Get-CarlaProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -in @('CarlaUE4.exe', 'CarlaUE4-Win64-Shipping.exe')
    })
}

$ownedServerProcess = $null
$ownedChildren = @{}
function Remember-OwnedCarlaChildren {
    if ($null -eq $script:ownedServerProcess) { return }
    foreach ($process in @(Get-CarlaProcesses)) {
        if ($process.ParentProcessId -eq $script:ownedServerProcess.Id -or
            $script:ownedChildren.ContainsKey([int]$process.ParentProcessId)) {
            $script:ownedChildren[[int]$process.ProcessId] = $process.CreationDate
        }
    }
}
function Stop-OwnedCarlaServer {
    if ($null -eq $script:ownedServerProcess) { return }
    Remember-OwnedCarlaChildren
    if (-not $script:ownedServerProcess.HasExited) {
        & taskkill.exe /PID $script:ownedServerProcess.Id /T /F | Out-Null
    }
    # The bootstrap can exit before its shipping child; retain proven ownership.
    foreach ($process in @(Get-CarlaProcesses)) {
        if ($script:ownedChildren.ContainsKey([int]$process.ProcessId) -and
            $script:ownedChildren[[int]$process.ProcessId] -eq $process.CreationDate) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-CarlaReady {
    # A connection timeout is normal while UE4 is still loading.  With the
    # script-wide Stop policy, PowerShell otherwise promotes Python's expected
    # stderr into a terminating NativeCommandError and aborts the launcher.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -c "import sys; sys.path.insert(0,sys.argv[1]); from stack_supervisor import carla_rpc_probe; sys.exit(0 if carla_rpc_probe('127.0.0.1',2000) else 1)" (Join-Path $appRoot 'app') 2>$null
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
    $_.Name -match '^python' -and $_.CommandLine -match '(spawn_car|scenic_drive|neural_drive_agent|stack_supervisor|collect_expert_data)\.py'
}
if ($activeDriver) {
    throw 'Another cockpit or supervised driver is active. Close it or run stop_stack.cmd first.'
}
& $python (Join-Path $appRoot 'app\runtime\health.py')
if ($LASTEXITCODE -ne 0) { throw 'The thermal/hardware cooldown is still active.' }

if (Get-CarlaProcesses) {
    if ($RequireFreshServer -or $Mode -eq 'scenic') {
        throw 'Close the existing CARLA session before switching driving profiles.'
    }
    Write-Host 'Checking the existing CARLA server...'
    if (-not (Test-CarlaReady)) {
        throw 'An existing CARLA server is unresponsive. Close its owning session before starting practice.'
    }
}

$ownedServer = -not [bool](Get-CarlaProcesses)
try {
if ($ownedServer) {
    Write-Host "Starting one CARLA server for $Mode mode..."
    $quality = if ($Mode -eq 'presentation' -or $FullGraphics) { 'Epic' } else { 'Low' }
    $serverArguments = @('-RenderOffScreen', "-$RenderApi", "-quality-level=$quality", '-nosound',
                        '-NoVSync', '-NoBloom', '-NoMotionBlur', '-ResX=320',
                        '-ResY=180', '-fps=20', '-unattended', '-carla-rpc-port=2000')
    if ($FullGraphics) {
        $serverArguments = if ($CameraProfile -eq 'triple') {
            @('-RenderOffScreen', "-$RenderApi", '-quality-level=Epic', '-NoVSync',
              "-ResX=$displayWidth", "-ResY=$displayHeight", "-fps=$displayFps",
              '-unattended', '-carla-rpc-port=2000', "-ExecCmds=`"t.MaxFPS $displayFps`"")
        } else {
            @('-windowed', "-$RenderApi", '-quality-level=Epic', '-NoVSync',
              "-ResX=$displayWidth", "-ResY=$displayHeight", "-fps=$displayFps",
              '-carla-rpc-port=2000', "-ExecCmds=`"t.MaxFPS $displayFps`"")
        }
    }
    if ($LowScenery) {
        $serverArguments += '-ExecCmds="t.MaxFPS 20,r.ViewDistanceScale 0.4,r.ShadowQuality 0,r.SSR.Quality 0,r.BloomQuality 0,r.MotionBlurQuality 0,r.VolumetricFog 0,r.DetailMode 0,foliage.DensityScale 0,grass.DensityScale 0,foliage.LODDistanceScale 0.5"'
    }
    elseif ($Mode -eq 'presentation') {
        $serverArguments += '-ExecCmds="t.MaxFPS 20,sg.ShadowQuality 1,sg.PostProcessQuality 1,sg.EffectsQuality 1,sg.FoliageQuality 2,r.ViewDistanceScale 0.7,r.MotionBlurQuality 0"'
    }
    $windowStyle = if ($FullGraphics -and $CameraProfile -ne 'triple') { 'Normal' } else { 'Hidden' }
    if ($Mode -eq 'scenic') {
        $serverArguments = @('-windowed', "-$RenderApi", '-quality-level=Epic',
                             '-ResX=1280', '-ResY=720', '-fps=30', '-carla-rpc-port=2000',
                             '-ExecCmds="t.MaxFPS 30"')
        $windowStyle = 'Normal'
    }
    $ownedServerProcess = Start-Process -PassThru -FilePath $server -ArgumentList $serverArguments `
        -WorkingDirectory $CarlaRoot -WindowStyle $windowStyle `
        -RedirectStandardOutput (Join-Path $logDir "$runName-server.log") `
        -RedirectStandardError (Join-Path $logDir "$runName-server.error.log")
}

Write-Host 'Waiting for the CARLA world to finish loading...'
$deadline = (Get-Date).AddSeconds(180)
$ready = $false
$missingProcessChecks = 0
while ((Get-Date) -lt $deadline) {
    Remember-OwnedCarlaChildren
    if (-not (Test-CarlaStartupAlive -OwnedProcess $ownedServerProcess -FindProcesses { Get-CarlaProcesses })) {
        $missingProcessChecks++
        if ($missingProcessChecks -lt 3) {
            Start-Sleep -Seconds 1
            continue
        }
        $detail = Get-CarlaStartupExitDetail -OwnedProcess $ownedServerProcess
        $failurePath = Join-Path $logDir "$runName-startup-failure.txt"
        $detail | Set-Content -LiteralPath $failurePath -Encoding UTF8
        throw "CARLA stopped before the world became ready. $detail Details: $failurePath"
    }
    $missingProcessChecks = 0
    if (Test-CarlaReady) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 3
}
if (-not $ready) {
    if ($ownedServer) { Stop-OwnedCarlaServer }
    throw "CARLA did not become ready within 180 seconds. See $logDir and the latest Unreal crash report."
}

$env:PYTHONPATH = "$appRoot\app;$env:PYTHONPATH"
if ($CameraProfile -eq 'map' -and $Mode -ne 'scenic' -and -not $FullGraphics) {
    & $python -c "import sys, carla; from simulation.environment import prepare_state_world; client=carla.Client('127.0.0.1',2000); client.set_timeout(45); world=prepare_state_world(client,carla,sys.argv[1]); print('[environment] camera-free world ready: '+world.get_map().name)" $Map
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the camera-free input environment.' }
}
Write-Host "CARLA is ready. Starting $Mode mode on $Map."
if ($largeMapGraphics) {
    Write-Host "Large-map graphics profile: Epic, all scenery layers, ${displayWidth}x${displayHeight}, ${displayFps} FPS target."
}
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
    $mirrorCameraFps = 2
    if ($FullGraphics) {
        $sceneryArguments += '--full-graphics'
        $frontCameraFps = if ($largeMapGraphics) { 6 } else { 10 }
        if ($threeCameraGraphics) {
            # DX12 + client-paced ticks sustained 15/5/5 fps for 60 s (2026-10-06 probe).
            $frontCameraFps = if ($largeMapGraphics) { 8 } else { 15 }
            $mirrorCameraFps = if ($largeMapGraphics) { 3 } else { 5 }
        }
    }
    if ($Mode -eq 'training') {
        $sceneryArguments += @('--human-demo', '--human-target-episodes', "$Episodes",
                               '--human-output-dir', $OutputDir, '--map-open-on-start')
    }
    if ($Mode -eq 'scenic') {
        $serverIds = @((Get-CarlaProcesses).ProcessId)
        $scenicArguments = @('--map', $Map, '--max-runtime-seconds', "$MaxRuntimeSeconds")
        if ($SpawnIndex -ge 0) { $scenicArguments += @('--spawn-index', "$SpawnIndex") }
        & $python -u (Join-Path $appRoot 'app\scenic_drive.py') @scenicArguments --server-pids @serverIds 2>&1 |
            Tee-Object -FilePath (Join-Path $logDir "$runName-driving.log")
    }
    elseif ($Mode -eq 'expert') {
        & $python -u (Join-Path $appRoot 'app\collect_expert_data.py') --carla-root $CarlaRoot `
            --map $Map --headless --output-dir $OutputDir --episodes $Episodes --max-ticks $MaxTicks 2>&1 |
            Tee-Object -FilePath (Join-Path $logDir "$runName-expert.log")
    }
    else {
    $serverIds = if ($ownedServer) { @((Get-CarlaProcesses).ProcessId) } else { @() }
    if ($ScriptedKeys) {
        # Diagnostic only: replays keys inside the cockpit, never sends desktop input.
        if (-not (Test-Path -LiteralPath $ScriptedKeys)) { throw "Scripted key file is missing: $ScriptedKeys" }
        $routeArguments += @('--scripted-keys', (Resolve-Path -LiteralPath $ScriptedKeys).Path)
    }
    & $python -u $cockpit --map $Map --camera-profile $CameraProfile @sceneryArguments @routeArguments `
        --carla-window-pids @serverIds `
        --window-width $displayWidth --window-height $displayHeight --target-fps $displayFps `
        --camera-fps $frontCameraFps --mirror-camera-fps $mirrorCameraFps --input-latch-ms 35 `
        --route-speed-kmh 30 --graphics-throttle-start-kmh 32 `
        --graphics-speed-cap-kmh 48 --visual-austerity-start-kmh 32 `
        --visual-austerity-resume-kmh 26 --runtime-rpc-timeout $(if ($largeMapGraphics) { 20 } elseif ($FullGraphics) { 10 } else { 2 }) `
        --max-runtime-seconds $MaxRuntimeSeconds `
        --screenshot-path (Join-Path $logDir "$runName-$CameraProfile.png") 2>&1 |
        Tee-Object -FilePath (Join-Path $logDir "$runName-cockpit.log")
    }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        throw "The $Mode session exited with code $LASTEXITCODE."
    }
}
finally {
    if ($ownedServer) {
        Write-Host "Stopping the $Mode CARLA server cleanly."
        Stop-OwnedCarlaServer
    }
}

}
finally {
    if ($leaseAcquired) { $sessionMutex.ReleaseMutex() }
    $sessionMutex.Dispose()
}
