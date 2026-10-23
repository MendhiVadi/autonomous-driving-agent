param(
    [string]$CarlaRoot = '',
    [string]$Map = '',
    [ValidateSet('dx11', 'dx12', 'vulkan')][string]$RenderApi = 'dx11',
    [double]$MaxRuntimeSeconds = 0,
    [ValidateSet('manual', 'gateway')][string]$Mode = 'manual',
    [ValidateRange(1, 65535)][int]$GatewayPort = 8765,
    [string]$GatewayBind = '127.0.0.1',
    [string]$PeerAddress = '',
    [switch]$Tls,
    [switch]$SingleSession,
    [switch]$NoInput,
    [ValidateRange(-1,100000)][int]$SpawnIndex = -1,
    [ValidateRange(30, 600)][int]$StartupTimeoutSeconds = 240,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config\runtime.json') -Raw | ConvertFrom-Json
if (-not $CarlaRoot) {
    $CarlaRoot = if ($env:CARLA_ROOT) { $env:CARLA_ROOT } else { [Environment]::ExpandEnvironmentVariables($config.carla_root) }
}
$CarlaRoot = [IO.Path]::GetFullPath($CarlaRoot)
if (-not $Map) { $Map = $config.map }
if ([double]::IsNaN($MaxRuntimeSeconds) -or [double]::IsInfinity($MaxRuntimeSeconds) -or $MaxRuntimeSeconds -lt 0) {
    throw 'MaxRuntimeSeconds must be finite and non-negative.'
}
$localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $localPython -PathType Leaf) { $localPython } else { Join-Path $CarlaRoot 'carla_env\Scripts\python.exe' }
$server = Join-Path $CarlaRoot 'CarlaUE4.exe'
foreach ($path in @($python, $server, (Join-Path $projectRoot 'run.py'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required file: $path" }
}
& $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); import carla; from sim_host import manual, profiles, gateway, carla_backend; print('Host imports OK; full graphics; no model training.')" (Join-Path $projectRoot 'src')
if ($LASTEXITCODE -ne 0) { throw 'Host import check failed.' }
$worldPath = & $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from sim_host.profiles import installed_map_path; print(installed_map_path(sys.argv[2],sys.argv[3]))" (Join-Path $projectRoot 'src') $CarlaRoot $Map
if ($LASTEXITCODE -ne 0) { throw 'Installed map preflight failed.' }
if ($Check) { exit 0 }
if ($Mode -eq 'gateway' -and -not $Tls -and (-not $env:SIM_GATEWAY_TOKEN -or $env:SIM_GATEWAY_TOKEN.Length -lt 32 -or $env:SIM_GATEWAY_TOKEN -match '[^\x00-\x7F]')) {
    throw 'Set SIM_GATEWAY_TOKEN to a random secret of at least 32 ASCII characters before launching the gateway.'
}
if ($Mode -eq 'gateway') {
    $peerForCheck = if ($PeerAddress) { $PeerAddress } else { '-' }
    & $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from sim_host.transport import local_address,server_context,load_token; host=local_address(sys.argv[2]); tls=sys.argv[3]=='True'; peer='' if sys.argv[4]=='-' else sys.argv[4]; assert host=='127.0.0.1' or (tls and peer), 'LAN needs TLS and an explicit peer'; local_address(peer) if peer else None; server_context(sys.argv[5]) if tls else None; load_token(sys.argv[5]) if tls else None" (Join-Path $projectRoot 'src') $GatewayBind ([string][bool]$Tls) $peerForCheck (Join-Path $projectRoot 'credentials')
    if ($LASTEXITCODE -ne 0) { throw 'Secure gateway preflight failed.' }
}

. (Join-Path $PSScriptRoot 'carla_startup_state.ps1')
function Get-CarlaProcesses {
    @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('CarlaUE4.exe', 'CarlaUE4-Win64-Shipping.exe') })
}
$mutex = [Threading.Mutex]::new($false, 'Local\AutonomousDrivingAgent.Runtime')
$acquired = $false
$ownedServer = $null
$children = @{}
try {
    try { $acquired = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw 'Another managed driving session is active.' }
    if (Get-CarlaProcesses) { throw 'Close the running CARLA session before starting this host.' }
    & $python -I -B (Join-Path $projectRoot 'src\sim_host\health.py')
    if ($LASTEXITCODE -ne 0) { throw 'Hardware cooldown check failed.' }
    $logRoot = Join-Path $projectRoot 'logs'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $arguments = & $python -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from sim_host.profiles import PRESENTATION; print(PRESENTATION.server_command_line(sys.argv[2]))" (Join-Path $projectRoot 'src') $RenderApi
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare graphics settings.' }
    # This Windows shipping build ignores command-line map overrides. Validate
    # the installed path above; the owned client selects the map via CARLA RPC.
    $engineLog = Join-Path $logRoot "$stamp-engine.log"
    $arguments = "$arguments -stdout -FullStdOutLogOutput -abslog=`"$engineLog`""
    Write-Host "Starting CARLA for $Map with Epic graphics; logs: $logRoot ($stamp)"
    # This is the requested interactive simulator window, not a background helper.
    $ownedServer = Start-Process -FilePath $server -ArgumentList $arguments -WorkingDirectory $CarlaRoot -WindowStyle Normal -PassThru -RedirectStandardOutput (Join-Path $logRoot "$stamp-server.log") -RedirectStandardError (Join-Path $logRoot "$stamp-server.error.log")
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $ready = $false
    $missing = 0
    while ((Get-Date) -lt $deadline) {
        $processes = @(Get-CarlaProcesses)
        foreach ($process in $processes) {
            if ($process.ParentProcessId -eq $ownedServer.Id -or $children.ContainsKey([int]$process.ParentProcessId)) {
                if (-not $children.ContainsKey([int]$process.ProcessId)) {
                    $children[[int]$process.ProcessId] = Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
                }
            }
        }
        if (-not (Test-CarlaStartupAlive -OwnedProcess $ownedServer -FindProcesses { Get-CarlaProcesses })) {
            $missing++
            if ($missing -ge 3) { throw (Get-CarlaStartupExitDetail -OwnedProcess $ownedServer) }
        } else { $missing = 0 }
        if (Test-CarlaRpcReady -PythonPath $python) { $ready = $true; break }
        Write-Host 'Waiting for the CARLA world...'
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "CARLA did not become ready within $StartupTimeoutSeconds seconds. See $engineLog" }
    $serverIds = @($ownedServer.Id) + @($children.Keys)
    $clientArgs = @('-I', '-B', '-X', 'faulthandler', (Join-Path $projectRoot 'run.py'), '--map', $Map,
                    '--max-runtime-seconds', $MaxRuntimeSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
                    '--server-pids') + $serverIds
    if ($NoInput) { $clientArgs += '--no-input' }
    if ($SpawnIndex -ge 0) { $clientArgs += @('--spawn-index', $SpawnIndex) }
    if ($Mode -eq 'gateway') {
        $clientArgs = @('-I', '-B', '-X', 'faulthandler', (Join-Path $projectRoot 'gateway.py'), '--backend', 'carla',
                        '--map', $Map, '--port', $GatewayPort,
                        '--max-runtime-seconds', $MaxRuntimeSeconds.ToString([Globalization.CultureInfo]::InvariantCulture))
        $clientArgs += @('--bind', $GatewayBind)
        if ($Tls) { $clientArgs += '--tls' }
        if ($PeerAddress) { $clientArgs += @('--allow-peer', $PeerAddress) }
        if ($SingleSession) { $clientArgs += '--single-session' }
        if ($SpawnIndex -ge 0) { $clientArgs += @('--spawn-index', $SpawnIndex) }
    }
    Invoke-CarlaLoggedClient -PythonPath $python -Arguments $clientArgs -LogPath (Join-Path $logRoot "$stamp-driving.log")
} finally {
    # Only terminate processes whose handles were captured from this launch.
    try {
        foreach ($process in @($children.Values) + @($ownedServer)) {
            if ($null -eq $process) { continue }
            try {
                if (-not $process.HasExited) {
                    $process.Kill()
                    if (-not $process.WaitForExit(5000)) {
                        Write-Warning "Owned process $($process.Id) did not exit within five seconds."
                    }
                }
            } catch {
                if (-not $process.HasExited) { Write-Warning "Owned process cleanup failed: $_" }
            }
        }
    } finally {
        if ($acquired) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
