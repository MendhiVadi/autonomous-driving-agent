function Invoke-CarlaLoggedClient {
    param([string]$PythonPath, [object[]]$Arguments, [string]$LogPath)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $PythonPath @Arguments 2>&1 | Tee-Object -FilePath $LogPath -ErrorAction Stop
        $clientExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($clientExitCode -ne 0) { throw "Driving client exited with code $clientExitCode." }
}

function Test-CarlaRpcReady {
    param([string]$PythonPath)
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 treats native stderr as a terminating error
        # under Stop. Connection timeouts during startup must be retryable.
        $ErrorActionPreference = 'Continue'
        $null = & $PythonPath -I -B -c "import carla; c=carla.Client('127.0.0.1',2000); c.set_timeout(2); c.get_world()" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

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
