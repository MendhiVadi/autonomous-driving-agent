param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath,
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,
    [Parameter(Mandatory = $true)]
    [string]$CarlaRoot,
    [Parameter(Mandatory = $true)]
    [string]$LogDir,
    [string]$SupervisorExtraArgs = ""
)

$ErrorActionPreference = "Stop"
$taskName = "AutonomousDrivingAgent_Supervisor"
$supervisorPath = Join-Path $AppRoot "app\stack_supervisor.py"

foreach ($path in @($PythonPath, $supervisorPath, $CarlaRoot, $LogDir)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required supervisor path does not exist: $path"
    }
}

function Quote-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
    (Quote-TaskArgument $supervisorPath),
    "--carla-root", (Quote-TaskArgument $CarlaRoot),
    "--log-dir", (Quote-TaskArgument $LogDir)
)
if ($SupervisorExtraArgs.Trim()) {
    $arguments += @($SupervisorExtraArgs.Trim() -split "\s+")
}

$action = New-ScheduledTaskAction -Execute $PythonPath -Argument ($arguments -join " ") -WorkingDirectory $AppRoot
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddYears(1))
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

$deadline = (Get-Date).AddSeconds(20)
do {
    $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^python' -and
            $_.CommandLine -match 'stack_supervisor\.py'
        })
    if ($running.Count) {
        Write-Output "Supervisor process started (PID $($running[-1].ProcessId))."
        exit 0
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
throw "The supervisor task did not create a live process. LastTaskResult=$($info.LastTaskResult)"
