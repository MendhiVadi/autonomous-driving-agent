$ErrorActionPreference = 'Stop'
$appRoot = (Split-Path -Parent $PSScriptRoot)
$supervisorPath = Join-Path $appRoot 'app\stack_supervisor.py'
$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($supervisorPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
})
if (-not $active.Count) { Write-Host 'No supervised session is running. Close a practice window with Esc.'; exit 0 }
$request = Join-Path $appRoot 'logs\stop.request'
New-Item -ItemType File -Path $request -Force | Out-Null
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Milliseconds 500
    $remaining = @($active | Where-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue })
} while ($remaining.Count -and (Get-Date) -lt $deadline)
if ($remaining.Count) { throw 'The supervisor did not finish cleanup within 60 seconds. Inspect logs; no unrelated process was terminated.' }
Write-Host 'Supervised session stopped. Logs retained.'
