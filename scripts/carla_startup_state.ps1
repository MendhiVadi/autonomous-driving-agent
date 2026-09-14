function Test-CarlaStartupAlive {
    param([object]$OwnedProcess, [scriptblock]$FindProcesses)
    # The process handle is authoritative while it is alive. CIM can briefly
    # omit a newly started process and must not cause us to kill that process.
    if ($null -ne $OwnedProcess -and -not $OwnedProcess.HasExited) { return $true }
    # The bootstrap executable can hand over to the shipping executable.
    return (@(& $FindProcesses).Count -gt 0)
}

function Get-CarlaStartupExitDetail {
    param([object]$OwnedProcess)
    if ($null -eq $OwnedProcess -or -not $OwnedProcess.HasExited) {
        return 'No exited owned process was available; Windows could not observe a CARLA process.'
    }
    $code = [int]$OwnedProcess.ExitCode
    $unsigned = [BitConverter]::ToUInt32([BitConverter]::GetBytes($code), 0)
    return ('Owned CARLA process {0} exited with code {1} (0x{2:X8}).' -f $OwnedProcess.Id, $code, $unsigned)
}
