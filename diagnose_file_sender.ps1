$ErrorActionPreference = 'Stop'
Start-Transcript -LiteralPath (Join-Path $PSScriptRoot 'transfer-diagnostics.log') -Force
try {
    Get-SmbShare -Name Laptop2Transfer | Format-List Name,Path,ShareState,EncryptData,ScopeName
    Get-SmbShareAccess -Name Laptop2Transfer | Format-Table AccountName,AccessControlType,AccessRight
    Get-SmbServerConfiguration | Format-List EnableSMB1Protocol,EnableSMB2Protocol,RejectUnencryptedAccess,RequireSecuritySignature,EnableSecuritySignature
    Get-SmbSession | Select-Object ClientComputerName,ClientUserName,NumOpens,Dialect | Format-Table
    Get-NetTCPConnection -LocalPort 445 | Format-Table LocalAddress,RemoteAddress,State
    Get-NetConnectionProfile -InterfaceAlias Ethernet | Format-List InterfaceAlias,NetworkCategory
    Get-NetFirewallProfile | Format-Table Name,Enabled,DefaultInboundAction,AllowInboundRules,AllowLocalFirewallRules
    Get-NetFirewallRule -Name ADA-Ethernet-Laptop2Transfer -PolicyStore ActiveStore | Format-List Name,Enabled,Direction,Action,Profile,PolicyStoreSourceType
    Get-NetFirewallRule -Name ADA-Ethernet-Laptop2Transfer -PolicyStore ActiveStore | Get-NetFirewallAddressFilter | Format-List LocalAddress,RemoteAddress
    $since = (Get-Date).AddHours(-1)
    foreach ($log in @('Microsoft-Windows-SMBServer/Operational','Microsoft-Windows-SMBServer/Security','Microsoft-Windows-SMBServer/Connectivity')) {
        Write-Output "EVENT LOG: $log"
        $events = Get-WinEvent -FilterHashtable @{LogName=$log;StartTime=$since} -MaxEvents 8 -ErrorAction SilentlyContinue
        if ($events) { $events | Select-Object TimeCreated,Id,Message | Format-List }
        else { Write-Output 'No recent accessible events.' }
    }
    $failedLogons = Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625;StartTime=$since} -MaxEvents 20 -ErrorAction SilentlyContinue
    foreach ($event in $failedLogons) {
        $xml = [xml]$event.ToXml()
        $data = @{}
        foreach ($item in $xml.Event.EventData.Data) { $data[$item.Name] = $item.'#text' }
        if ($data['IpAddress'] -eq '169.254.102.28') {
            [pscustomobject]@{Time=$event.TimeCreated;IP=$data['IpAddress'];Status=$data['Status'];SubStatus=$data['SubStatus'];LogonType=$data['LogonType'];Account=$data['TargetUserName'];Domain=$data['TargetDomainName']} | Format-List
        }
    }
    Write-Output 'DIAGNOSTICS COMPLETE'
} catch { Write-Output "FAILED: $($_.Exception.Message)" }
finally { Stop-Transcript }
