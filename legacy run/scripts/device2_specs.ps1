$ErrorActionPreference = "Stop"
Write-Host "=== OS ==="
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture
Write-Host "=== Computer ==="
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory
Write-Host "=== CPU ==="
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Write-Host "=== GPU ==="
Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion
Write-Host "=== Wired network ==="
Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object Name,InterfaceDescription,Status,LinkSpeed,MacAddress
Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway
