param(
    [string]$HealthUrl = 'http://localhost:8101/health',
    [int]$TimeoutSeconds = 90,
    [int]$PollSeconds = 2
)

$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

Write-Host "Waiting for backend health at $HealthUrl" -ForegroundColor Cyan

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
        if ($response.status -eq 'ok') {
            Write-Host 'Backend health check is OK.' -ForegroundColor Green
            $response | ConvertTo-Json -Depth 5
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds $PollSeconds
    }
}

throw "Timed out waiting for backend health at $HealthUrl"
