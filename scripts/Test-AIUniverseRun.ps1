param(
    [string]$BaseUrl = "http://localhost:8101/api/v1",
    [int]$PollSeconds = 2,
    [int]$MaxWaitSeconds = 90,
    [switch]$ShowPayload
)

$ErrorActionPreference = "Stop"

function Get-LatestStockUniverseRun {
    param(
        [string]$Url
    )

    try {
        Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 30
    }
    catch {
        $null
    }
}

$runUrl = "$BaseUrl/universe/stock/run"
$triggerUrl = "$BaseUrl/controls/universe/run-once"

$before = Get-LatestStockUniverseRun -Url $runUrl
$beforeId = if ($before -and $null -ne $before.id) { [int]$before.id } else { 0 }
$beforeResolvedAt = if ($before) { [string]$before.resolved_at } else { "" }

$body = @{
    asset_class = "stock"
    force       = $true
} | ConvertTo-Json

Write-Host "Triggering stock AI universe run..." -ForegroundColor Cyan

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

$triggerResponse = Invoke-RestMethod `
    -Method Post `
    -Uri $triggerUrl `
    -ContentType "application/json" `
    -Body $body `
    -TimeoutSec 90

Write-Host "Trigger response:" -ForegroundColor DarkCyan
$triggerResponse | ConvertTo-Json -Depth 6

$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
$latest = $null
$changed = $false

do {
    Start-Sleep -Seconds $PollSeconds
    $latest = Get-LatestStockUniverseRun -Url $runUrl

    if ($null -eq $latest) {
        continue
    }

    $latestId = 0
    try {
        $latestId = [int]$latest.id
    }
    catch {
        $latestId = 0
    }

    $latestResolvedAt = [string]$latest.resolved_at

    if (($latestId -gt $beforeId) -or ($latestResolvedAt -ne $beforeResolvedAt)) {
        $changed = $true
        break
    }
}
while ((Get-Date) -lt $deadline)

$stopwatch.Stop()

if (-not $changed -or $null -eq $latest) {
    throw "Timed out waiting for a new stock universe run result after $MaxWaitSeconds seconds."
}

$payload = $latest.payload
$resolution = $null
$candidateCount = $null

if ($payload) {
    if ($payload.PSObject.Properties.Name -contains "resolution") {
        $resolution = $payload.resolution
    }
    if ($payload.PSObject.Properties.Name -contains "candidate_count") {
        $candidateCount = $payload.candidate_count
    }
}

$aiOutcome = switch ($latest.source) {
    "ai"       { "AI succeeded" }
    "fallback" { if ($latest.last_error) { "AI failed, fallback used" } else { "Fallback used" } }
    default    { "Unknown" }
}

$result = [pscustomobject]@{
    elapsed_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 2)
    run_id          = $latest.id
    trade_date      = $latest.trade_date
    status          = $latest.status
    source          = $latest.source
    ai_outcome      = $aiOutcome
    last_error      = $latest.last_error
    resolution      = $resolution
    candidate_count = $candidateCount
    resolved_at     = $latest.resolved_at
    snapshot_path   = $latest.snapshot_path
}

Write-Host ""
Write-Host "Latest stock universe run:" -ForegroundColor Green
$result | Format-List

if ($ShowPayload -and $payload) {
    Write-Host ""
    Write-Host "Raw payload:" -ForegroundColor Yellow
    $payload | ConvertTo-Json -Depth 8
}