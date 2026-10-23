[CmdletBinding()]
param([switch]$Recreate)

$ErrorActionPreference = 'Stop'
$report = Join-Path $PSScriptRoot 'transfer-setup.log'
Start-Transcript -LiteralPath $report -Force
try {
    $identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this script as Administrator.'
    }
    $folder = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'transfer')).Path
    $adapter = Get-NetAdapter -Name 'Ethernet'
    if ($adapter.Status -ne 'Up' -or $adapter.InterfaceDescription -notlike '*Realtek USB GbE*') {
        throw 'The expected Realtek Ethernet cable adapter is not connected.'
    }
    $addresses = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '169.254.*' -and $_.AddressState -eq 'Preferred' })
    if ($addresses.Count -ne 1) { throw 'The Ethernet address changed; inspect it before configuring sharing.' }
    $address = $addresses[0].IPAddress
    $shareName = 'Laptop2Transfer'
    $account = 'MENDHI_VADI\medha'
    foreach ($requiredFile in @('laptop-2.zip', 'obsidian-vault.zip')) {
        if (-not (Test-Path -LiteralPath (Join-Path $folder $requiredFile) -PathType Leaf)) {
            throw "Required transfer file is missing: $requiredFile"
        }
    }
    if ((Get-Service LanmanServer).Status -ne 'Running') { Start-Service LanmanServer }
    # Add read/traverse access without removing existing NTFS permissions.
    & icacls.exe $folder /grant ($account + ':(OI)(CI)RX')
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant the sender account folder read access.' }
    $existing = Get-SmbShare -Name $shareName -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Path -ne $folder) { throw 'Share name already points to another folder.' }
        if ($Recreate) {
            $existing | Remove-SmbShare -Force -Confirm:$false
            $existing = $null
        }
    }
    if (-not $existing) {
        New-SmbShare -Name $shareName -Path $folder -ReadAccess $account -EncryptData $true -FolderEnumerationMode AccessBased | Out-Null
    } else {
        Grant-SmbShareAccess -Name $shareName -AccountName $account -AccessRight Read -Force | Out-Null
        Set-SmbShare -Name $shareName -EncryptData $true -Confirm:$false | Out-Null
    }
    $ruleName = 'ADA-Ethernet-Laptop2Transfer'
    $existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($existingRule) {
        Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -LocalAddress $address -RemoteAddress '169.254.102.28' -InterfaceAlias 'Ethernet' -Profile Any -EdgeTraversalPolicy Block | Out-Null
    } else {
        New-NetFirewallRule -Name $ruleName -DisplayName 'Laptop 2 file transfer on direct Ethernet' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -LocalAddress $address -RemoteAddress '169.254.102.28' -InterfaceAlias 'Ethernet' -Profile Any -EdgeTraversalPolicy Block | Out-Null
    }
    Get-SmbShare -Name $shareName | Format-List Name,Path,ShareState,EncryptData,ScopeName
    Get-SmbShareAccess -Name $shareName | Format-Table AccountName,AccessControlType,AccessRight
    Get-NetFirewallRule -Name $ruleName | Format-List Name,Enabled,Direction,Action
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallAddressFilter | Format-List LocalAddress,RemoteAddress
    $unc = "\\$address\$shareName"
    try {
        Get-ChildItem -LiteralPath $unc | Format-Table Name,Length
        foreach ($requiredFile in @('laptop-2.zip', 'obsidian-vault.zip')) {
            $localHash = (Get-FileHash -LiteralPath (Join-Path $folder $requiredFile) -Algorithm SHA256).Hash
            $sharedHash = (Get-FileHash -LiteralPath (Join-Path $unc $requiredFile) -Algorithm SHA256).Hash
            if ($localHash -ne $sharedHash) { throw "Shared file hash mismatch: $requiredFile" }
        }
        Write-Output 'PASS: both ZIPs read through the SMB share and hashes match.'
    } catch {
        Write-Output "UNC CHECK FAILED: $($_.Exception.Message)"
    }
    Get-SmbSession | Select-Object ClientComputerName,ClientUserName,NumOpens | Format-Table
    Write-Output "RECEIVER PATH: \\$address\$shareName"
    Write-Output 'SUCCESS: sender configured. Receiving-PC access remains to be tested.'
} catch {
    Write-Output "FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    Stop-Transcript
}
