<#
.SYNOPSIS
Start one managed CARLA session for this project's driving modes.

.DESCRIPTION
Modes:
  manual      Full-graphics manual car in CARLA's own window (run_car.cmd).
  neural      Neural-network driving cockpit with a destination map
              (run_neural.cmd and run_large_map_neural.cmd): three Epic
              cameras from an offscreen DX12 server. -Lightweight uses the
              camera-free map cockpit instead (no 3D rendering at all).
  expert      Record CARLA BasicAgent demonstrations for training (no graphics).
  human-demo  Record your own demonstrations in the map cockpit.

The launcher owns the CARLA server it starts and shuts it down afterwards.
It refuses to run while another CARLA session or cockpit is active.

.EXAMPLE
run_neural.cmd -Lightweight
run_car.cmd -Map Town05 -MaxRuntimeSeconds 60
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Mode expert
#>
param(
    [string]$CarlaRoot = '',
    [ValidateSet('manual', 'neural', 'expert', 'human-demo')][string]$Mode = 'neural',
    [string]$Map = 'Town02_Opt',
    [string]$RenderApi = '',
    [switch]$Lightweight,
    [double]$MaxRuntimeSeconds = 0,
    [int]$SpawnIndex = -1,
    [switch]$IgnoreHardwareCooldown,
    # neural mode
    [string]$RoutePolicy = '',
    [switch]$NoNeuralVisual,
    [switch]$NoLaneAssist,
    [string]$RouteDestination = '',
    [double]$RouteAheadMeters = 0,
    [string]$ScriptedKeys = '',
    [double]$DiagnosticYawOffset = 0,
    [string]$DiagnosticDisplace = '',
    # expert and human-demo modes
    [int]$Episodes = 12,
    [int]$MaxTicks = 2400,
    [string]$OutputDir = 'episodes/expert'
)

$ErrorActionPreference = 'Stop'
if ([double]::IsNaN($MaxRuntimeSeconds) -or [double]::IsInfinity($MaxRuntimeSeconds) -or $MaxRuntimeSeconds -lt 0) {
    throw 'MaxRuntimeSeconds must be finite and non-negative.'
}
if ($RenderApi -and $RenderApi -notin @('dx11', 'dx12', 'vulkan')) { throw 'RenderApi must be dx11, dx12 or vulkan.' }
if ($Map -notmatch '^[A-Za-z][A-Za-z0-9_]{1,63}$') { throw 'Map must be a plain CARLA map name such as Town02_Opt or Town13.' }

$appRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'environment.ps1')
. (Join-Path $PSScriptRoot 'carla_startup_state.ps1')
$CarlaRoot = Resolve-CarlaRoot $CarlaRoot
$env:CARLA_ROOT = $CarlaRoot
Set-Location -LiteralPath $appRoot

$sessionMutex = [Threading.Mutex]::new($false, 'Local\AutonomousDrivingAgent.Runtime')
$leaseAcquired = $false
try {
    try { $leaseAcquired = $sessionMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $leaseAcquired = $true }
    if (-not $leaseAcquired) { throw 'Another managed CARLA session is already active. Close it first.' }

    # ---------------------------------------------------------------- installation
    $server = Join-Path $CarlaRoot 'CarlaUE4.exe'
    if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
        throw ("CARLA 0.9.16 was not found at '$CarlaRoot'. Extract the CARLA_0.9.16 Windows package there, " +
               "set the CARLA_ROOT environment variable, or edit config\runtime.json.")
    }
    $python = Get-CarlaPython $CarlaRoot
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $setup = Join-Path $PSScriptRoot 'setup_environment.ps1'
        Write-Host "The project's Python environment does not exist yet: $python"
        Write-Host 'It holds the CARLA client, pygame, numpy, networkx and shapely, and takes a few minutes to create.'
        if ([Environment]::UserInteractive) {
            $answer = Read-Host 'Create it now? (y/n)'
            if ($answer -match '^(y|yes)$') {
                & $setup -CarlaRoot $CarlaRoot
                if ($LASTEXITCODE -ne 0 -and -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Environment setup failed.' }
            }
        }
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            throw "Create the environment first: powershell -ExecutionPolicy Bypass -File scripts\setup_environment.ps1"
        }
    }
    $largeMap = $Map -in @('Town11', 'Town12', 'Town13')
    if ($largeMap -and -not (Test-Path -LiteralPath (Join-Path $CarlaRoot "CarlaUE4\Content\Carla\Maps\$Map"))) {
        throw ("$Map is not installed. Download AdditionalMaps_0.9.16.zip from the CARLA release and run " +
               "scripts\install_additional_maps.ps1 -Force (see README).")
    }

    # ---------------------------------------------------------------- profile
    $logDir = Join-Path $appRoot 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $runName = $Mode + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $mapCockpit = ($Mode -eq 'human-demo') -or ($Mode -eq 'neural' -and $Lightweight)
    $cameraCockpit = ($Mode -eq 'neural') -and -not $Lightweight
    $cameraProfile = if ($cameraCockpit) { 'triple' } else { 'map' }
    # RGB cameras hang CARLA within seconds under DX11 on the Intel Arc 140V; DX12 ran
    # three Epic cameras for minutes (docs/CRASH_DIAGNOSIS.md). Camera-free modes keep DX11.
    if (-not $RenderApi) { $RenderApi = if ($cameraCockpit) { 'dx12' } else { 'dx11' } }
    $displayWidth = if ($cameraCockpit) { 960 } else { 1280 }
    $displayHeight = if ($cameraCockpit) { 540 } else { 720 }
    $displayFps = if ($cameraCockpit) { 15 } else { 20 }
    $frontCameraFps = if ($largeMap) { 8 } else { 15 }
    $mirrorCameraFps = if ($largeMap) { 3 } else { 5 }
    $rpcTimeout = if ($largeMap) { 20 } elseif ($cameraCockpit) { 10 } else { 2 }

    $routeArguments = @()
    if ($Mode -eq 'neural') {
        $env:CARLA_NEURAL_VISUAL = '0'   # the cockpit opens the activity page itself
        if (-not $RoutePolicy) { $RoutePolicy = Get-DefaultPolicyPath }
        if (-not (Test-Path -LiteralPath $RoutePolicy -PathType Leaf)) {
            throw "Neural policy is missing: $RoutePolicy. Put nn_policy_colab.json next to run_neural.cmd (see README)."
        }
        $RoutePolicy = (Resolve-Path -LiteralPath $RoutePolicy).Path
        # Validate the weights before spending minutes on simulator startup.
        & $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from learning.model import load_deployable_policy; m=load_deployable_policy(sys.argv[2],require_route_conditioned=True); import json; print('[policy] validated', json.dumps({'sizes': m.sizes}))" (Join-Path $appRoot 'app') $RoutePolicy
        if ($LASTEXITCODE -ne 0) { throw "Neural policy validation failed: $RoutePolicy" }
        Write-Host "Neural policy: $RoutePolicy"
        if ((Split-Path -Leaf $RoutePolicy) -eq 'nn_policy_bootstrap.json') {
            Write-Warning ('Using the bundled BOOTSTRAP policy, a small network distilled from a rule-based teacher ' +
                           'on synthetic states. It drives, but it is not the model trained on real CARLA ' +
                           'demonstrations. Copy your trained nn_policy_colab.json next to run_neural.cmd to use that instead.')
        }
        $routeArguments = @('--route-policy', $RoutePolicy, '--preload-route-policy')
        if (-not $RouteDestination -and -not $RouteAheadMeters) { $routeArguments += '--map-open-on-start' }
        if (-not $NoLaneAssist) { $routeArguments += '--neural-lane-assist' }
        if (-not $NoNeuralVisual) {
            $routeArguments += '--neural-visual'
            Write-Host 'The network activity page opens in your browser when the model loads. F8 reopens it.'
        }
        if ($RouteDestination) {
            $coordinates = $RouteDestination.Split(',')
            if ($coordinates.Count -ne 2) { throw 'RouteDestination must be x,y map coordinates.' }
            foreach ($coordinate in $coordinates) {
                $number = [double]::Parse($coordinate, [Globalization.CultureInfo]::InvariantCulture)
                if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { throw 'RouteDestination coordinates must be finite.' }
            }
            $routeArguments += @('--route-destination', $coordinates[0], $coordinates[1])
        }
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
        if ($ScriptedKeys) {
            # Diagnostic only: replays keys inside the cockpit, never sends desktop input.
            if (-not (Test-Path -LiteralPath $ScriptedKeys)) { throw "Scripted key file is missing: $ScriptedKeys" }
            $routeArguments += @('--scripted-keys', (Resolve-Path -LiteralPath $ScriptedKeys).Path)
        }
    }
    if ($Mode -eq 'human-demo') {
        $routeArguments = @('--human-demo', '--human-target-episodes', "$Episodes", '--human-output-dir', $OutputDir, '--map-open-on-start')
    }
    if ($SpawnIndex -ge 0 -and $Mode -ne 'expert') { $routeArguments += @('--spawn-index', "$SpawnIndex") }

    # ---------------------------------------------------------------- preflight
    function Get-CarlaProcesses {
        @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.Name -in @('CarlaUE4.exe', 'CarlaUE4-Win64-Shipping.exe')
        })
    }
    function Test-CarlaReady {
        # A connection timeout is normal while UE4 is still loading. With the script-wide
        # Stop policy, PowerShell would otherwise promote Python's expected stderr into a
        # terminating error and abort the launcher.
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from simulation.environment import carla_rpc_probe; sys.exit(0 if carla_rpc_probe('127.0.0.1',2000) else 1)" (Join-Path $appRoot 'app') 2>$null
            return $LASTEXITCODE -eq 0
        } catch { return $false } finally { $ErrorActionPreference = $previousPreference }
    }

    $activeDriver = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python' -and $_.CommandLine -match '(neural_cockpit|manual_drive|collect_expert_data)\.py'
    }
    if ($activeDriver) { throw 'Another cockpit or driver from this project is still running. Close it first.' }
    if (-not $IgnoreHardwareCooldown) {
        & $python -I -B (Join-Path $appRoot 'app\runtime\health.py')
        if ($LASTEXITCODE -ne 0) {
            throw ('Windows logged a thermal or hardware fault recently and the cooldown is still active. ' +
                   'Let the laptop cool down, or re-run with -IgnoreHardwareCooldown if you accept the risk.')
        }
    }
    $existing = @(Get-CarlaProcesses)
    if ($existing.Count) {
        throw ("A CARLA server is already running (PID " + (($existing | ForEach-Object { $_.ProcessId }) -join ', ') +
               "). This launcher owns its own server so graphics settings cannot leak between modes: " +
               "close that CARLA window (or end CarlaUE4 in Task Manager) and run again.")
    }

    # ---------------------------------------------------------------- server
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
        # The bootstrap exe can exit before its shipping child; retain proven ownership.
        foreach ($process in @(Get-CarlaProcesses)) {
            if ($script:ownedChildren.ContainsKey([int]$process.ProcessId) -and
                $script:ownedChildren[[int]$process.ProcessId] -eq $process.CreationDate) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if ($Mode -eq 'manual') {
        # CARLA's own window is the game view: Epic, 1280x720, 30 FPS cap.
        $serverArguments = @('-windowed', "-$RenderApi", '-quality-level=Epic', '-ResX=1280', '-ResY=720',
                             '-fps=30', '-carla-rpc-port=2000', '-ExecCmds="t.MaxFPS 30"')
        $windowStyle = 'Normal'
    }
    elseif ($cameraCockpit) {
        # Offscreen Epic server; the pygame cockpit is the only window.
        $serverArguments = @('-RenderOffScreen', "-$RenderApi", '-quality-level=Epic', '-NoVSync',
                             "-ResX=$displayWidth", "-ResY=$displayHeight", "-fps=$displayFps", '-unattended',
                             '-carla-rpc-port=2000', "-ExecCmds=`"t.MaxFPS $displayFps`"")
        $windowStyle = 'Hidden'
    }
    else {
        # Camera-free modes: the renderer only has to exist, not look good.
        $serverArguments = @('-RenderOffScreen', "-$RenderApi", '-quality-level=Low', '-nosound', '-NoVSync',
                             '-NoBloom', '-NoMotionBlur', '-ResX=320', '-ResY=180', '-fps=20', '-unattended',
                             '-carla-rpc-port=2000', '-ExecCmds="t.MaxFPS 20"')
        $windowStyle = 'Hidden'
    }
    Write-Host "Starting CARLA ($RenderApi) for $Mode mode on $Map ..."
    $ownedServerProcess = Start-Process -PassThru -FilePath $server -ArgumentList $serverArguments `
        -WorkingDirectory $CarlaRoot -WindowStyle $windowStyle `
        -RedirectStandardOutput (Join-Path $logDir "$runName-server.log") `
        -RedirectStandardError (Join-Path $logDir "$runName-server.error.log")
    try {
        Write-Host 'Waiting for the CARLA world to finish loading...'
        $deadline = (Get-Date).AddSeconds(180)
        $ready = $false
        $missingProcessChecks = 0
        while ((Get-Date) -lt $deadline) {
            Remember-OwnedCarlaChildren
            if (-not (Test-CarlaStartupAlive -OwnedProcess $ownedServerProcess -FindProcesses { Get-CarlaProcesses })) {
                $missingProcessChecks++
                if ($missingProcessChecks -lt 3) { Start-Sleep -Seconds 1; continue }
                $detail = Get-CarlaStartupExitDetail -OwnedProcess $ownedServerProcess
                $failurePath = Join-Path $logDir "$runName-startup-failure.txt"
                $detail | Set-Content -LiteralPath $failurePath -Encoding UTF8
                throw "CARLA stopped before the world became ready. $detail Details: $failurePath"
            }
            $missingProcessChecks = 0
            if (Test-CarlaReady) { $ready = $true; break }
            Start-Sleep -Seconds 3
        }
        if (-not $ready) { throw "CARLA did not become ready within 180 seconds. See $logDir and the latest Unreal crash report." }

        $env:PYTHONPATH = "$appRoot\app;$env:PYTHONPATH"
        if ($mapCockpit) {
            # The map cockpit drives on physics alone: switch rendering off before it starts.
            & $python -c "import sys, carla; from simulation.environment import prepare_state_world; client=carla.Client('127.0.0.1',2000); client.set_timeout(300); world=prepare_state_world(client,carla,sys.argv[1]); print('[environment] camera-free world ready: '+world.get_map().name)" $Map
            if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the camera-free world.' }
        }
        Write-Host "CARLA is ready. Starting $Mode mode on $Map."
        if ($cameraCockpit) {
            Write-Host "Cockpit: three Epic cameras, ${displayWidth}x${displayHeight}, ${displayFps} FPS target, $RenderApi."
        }
        # Keep Python stderr in the log without promoting each native stderr line into a
        # terminating PowerShell error; propagate the real process exit code instead.
        $ErrorActionPreference = 'Continue'
        $serverIds = @((Get-CarlaProcesses).ProcessId)
        if ($Mode -eq 'manual') {
            $manualArguments = @('--map', $Map, '--max-runtime-seconds', "$MaxRuntimeSeconds")
            if ($SpawnIndex -ge 0) { $manualArguments += @('--spawn-index', "$SpawnIndex") }
            & $python -u (Join-Path $appRoot 'app\manual_drive.py') @manualArguments --server-pids @serverIds 2>&1 |
                Tee-Object -FilePath (Join-Path $logDir "$runName-driving.log")
        }
        elseif ($Mode -eq 'expert') {
            & $python -u (Join-Path $appRoot 'app\collect_expert_data.py') --carla-root $CarlaRoot `
                --map $Map --headless --output-dir $OutputDir --episodes $Episodes --max-ticks $MaxTicks 2>&1 |
                Tee-Object -FilePath (Join-Path $logDir "$runName-expert.log")
        }
        else {
            $graphicsArguments = if ($cameraCockpit) { @('--full-graphics') } else { @() }
            & $python -u (Join-Path $appRoot 'app\neural_cockpit.py') --map $Map --camera-profile $cameraProfile `
                @graphicsArguments @routeArguments --carla-window-pids @serverIds `
                --window-width $displayWidth --window-height $displayHeight --target-fps $displayFps `
                --camera-fps $frontCameraFps --mirror-camera-fps $mirrorCameraFps --input-latch-ms 35 `
                --route-speed-kmh 30 --graphics-throttle-start-kmh 32 --graphics-speed-cap-kmh 48 `
                --visual-austerity-start-kmh 32 --visual-austerity-resume-kmh 26 `
                --runtime-rpc-timeout $rpcTimeout --max-runtime-seconds $MaxRuntimeSeconds `
                --screenshot-path (Join-Path $logDir "$runName-$cameraProfile.png") 2>&1 |
                Tee-Object -FilePath (Join-Path $logDir "$runName-cockpit.log")
        }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw "The $Mode session exited with code $LASTEXITCODE." }
    }
    finally {
        Write-Host "Stopping the $Mode CARLA server."
        Stop-OwnedCarlaServer
    }
}
finally {
    if ($leaseAcquired) { $sessionMutex.ReleaseMutex() }
    $sessionMutex.Dispose()
}
