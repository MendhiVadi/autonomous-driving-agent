param(
    [string]$CarlaRoot = $(if ($env:CARLA_ROOT) { $env:CARLA_ROOT } else {
        Join-Path $env:USERPROFILE 'Documents\CARLA\CARLA_0.9.16'
    })
)
$ErrorActionPreference = 'Stop'
$runtimeRoot = (Resolve-Path -LiteralPath $CarlaRoot).Path
foreach ($required in @('CarlaUE4.exe', 'carla_env\Scripts\python.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot $required))) {
        throw "Required CARLA installation file is missing: $required"
    }
}
$files = @('spawn_car.py', 'control_policy.py', 'manual_transmission.py', 'agent_drive.py')
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) {
        throw "Repository runtime source is missing: $name"
    }
}
$backupRoot = Join-Path $runtimeRoot ('project_runtime_backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
foreach ($name in $files) {
    $destination = Join-Path $runtimeRoot $name
    if (Test-Path -LiteralPath $destination) {
        Copy-Item -LiteralPath $destination -Destination (Join-Path $backupRoot $name)
    }
}
foreach ($name in $files) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $runtimeRoot $name)
}
Write-Host "Installed the project runtime into $runtimeRoot"
Write-Host "Previous runtime files were backed up to $backupRoot"
Write-Host 'Start run_practice.cmd from this repository for map-and-controls mode.'
