@echo off
setlocal
rem Stop the supervised stack cleanly. Before the supervisor existed the only
rem way to stop these detached processes was Task Manager, which is also why a
rem half-dead stack could sit around unnoticed.
rem
rem Everything here kills process TREES. CarlaUE4.exe is a shim that launches
rem CarlaUE4-Win64-Shipping.exe, and these venvs use a redirector python.exe
rem that re-executes the base interpreter as a child. Killing only the process
rem we can see leaves the real worker running - which is how a stale CARLA
rem server ended up holding port 2000 while a second one started.

set "APP_ROOT=%~dp0"

echo Stopping the stack supervisor...
powershell.exe -NoProfile -Command "$p = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'stack_supervisor\.py' }); if($p.Count){ $p | ForEach-Object { & taskkill /PID $_.ProcessId /T /F *>$null }; \"stopped $($p.Count) supervisor process(es)\" } else { 'supervisor was not running' }"

rem Sweep repeatedly. Killing a parent tree orphans grandchildren that a single
rem snapshot taken moments earlier did not list, so one pass is not enough.
echo Stopping any remaining stack processes...
powershell.exe -NoProfile -Command "$filter = { ($_.Name -match '^CarlaUE4') -or ($_.Name -match '^python' -and $_.CommandLine -match 'neural_drive_agent\.py|stack_supervisor\.py') }; $total = 0; for($pass = 1; $pass -le 4; $pass++){ $p = @(Get-CimInstance Win32_Process | Where-Object $filter); if(-not $p.Count){ break }; $p | ForEach-Object { & taskkill /PID $_.ProcessId /T /F *>$null }; $total += $p.Count; Start-Sleep -Seconds 2 }; $left = @(Get-CimInstance Win32_Process | Where-Object $filter); if($left.Count){ Write-Host \"WARNING: $($left.Count) process(es) survived:\"; $left | ForEach-Object { Write-Host \"  $($_.ProcessId) $($_.Name)\" }; exit 1 } else { Write-Host \"clean (stopped $total process(es))\" }"

rem Remove the persistent task registration after its process tree is gone.
powershell.exe -NoProfile -Command "Unregister-ScheduledTask -TaskName 'AutonomousDrivingAgent_Supervisor' -Confirm:$false -ErrorAction SilentlyContinue"

echo.
echo Done. Logs remain in "%APP_ROOT%logs".
endlocal
exit /b 0
