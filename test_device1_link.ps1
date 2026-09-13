param([string]$Device1Address = "10.42.0.1", [int]$CarlaPort = 2000)
Write-Host "Ping test to Device 1: $Device1Address"
Test-Connection -ComputerName $Device1Address -Count 2
Write-Host "CARLA RPC test on Device 1: $Device1Address`:$CarlaPort"
Test-NetConnection -ComputerName $Device1Address -Port $CarlaPort
