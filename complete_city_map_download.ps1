param(
    [string]$JobName = "CARLA Tartu city map 0.9.16",
    [string]$StatusPath = "C:\Users\medha\Documents\CARLA\downloads\tartu_download_status.txt"
)

while ($true) {
    $job = Get-BitsTransfer -Name $JobName -ErrorAction SilentlyContinue
    if (-not $job) {
        Set-Content -LiteralPath $StatusPath -Value "Download job was not found."
        exit 1
    }
    if ($job.JobState -eq "Transferred") {
        Complete-BitsTransfer -BitsJob $job
        Set-Content -LiteralPath $StatusPath -Value "Download completed and finalized."
        exit 0
    }
    if ($job.JobState -in @("Error", "TransientError", "Cancelled")) {
        Set-Content -LiteralPath $StatusPath -Value ("Download stopped: " + $job.JobState)
        exit 1
    }
    $percent = if ($job.BytesTotal -gt 0 -and $job.BytesTotal -lt [uint64]::MaxValue) {
        [math]::Round(100 * $job.BytesTransferred / $job.BytesTotal, 1)
    } else {
        0
    }
    Set-Content -LiteralPath $StatusPath -Value ("Downloading: " + $percent + "%")
    Start-Sleep -Seconds 15
}
