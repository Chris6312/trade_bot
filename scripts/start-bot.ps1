#Requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipMigrations,
    [switch]$NoFrontend,
    [switch]$NoLogTabs,
    [switch]$Force,
    [switch]$KeepKillSwitchEnabled,
    [int]$PostgresTimeoutSeconds = 120,
    [int]$BackendTimeoutSeconds = 120,
    [int]$FrontendTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    $gitRoot = git rev-parse --show-toplevel 2>$null
    if ($gitRoot) {
        return ($gitRoot | Select-Object -First 1).Trim()
    }

    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Get-EnvMap {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $map = @{}
    if (-not (Test-Path $Path)) {
        return $map
    }

    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) {
            continue
        }

        $parts = $trimmed.Split('=', 2)
        $map[$parts[0].Trim()] = $parts[1].Trim()
    }

    return $map
}

function Get-SettingValue {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Map,
        [Parameter(Mandatory = $true)]
        [string]$Key,
        [Parameter(Mandatory = $true)]
        [string]$DefaultValue
    )

    if ($Map.ContainsKey($Key) -and $Map[$Key]) {
        return $Map[$Key]
    }

    return $DefaultValue
}

function Assert-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Resolve-PythonExe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }

    throw 'Python was not found. Activate .venv or install Python before running Start-Bot.ps1.'
}

function Get-RunningServices {
    return @(docker compose ps --status running --services 2>$null)
}

function Test-ServiceRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    return $ServiceName -in (Get-RunningServices)
}

function Get-ContainerInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $containerId = (docker compose ps -q $ServiceName 2>$null | Select-Object -First 1)
    if (-not $containerId) {
        return $null
    }

    $containerPidValue = docker inspect --format '{{.State.Pid}}' $containerId 2>$null
    $containerNameValue = docker inspect --format '{{.Name}}' $containerId 2>$null
    $containerStatusValue = docker inspect --format '{{.State.Status}}' $containerId 2>$null

    return [pscustomobject]@{
        service     = $ServiceName
        containerId = $containerId.Trim()
        container   = ($containerNameValue | Select-Object -First 1).ToString().Trim().TrimStart('/')
        pid         = ($containerPidValue | Select-Object -First 1).ToString().Trim()
        status      = ($containerStatusValue | Select-Object -First 1).ToString().Trim()
    }
}

function Wait-ForPostgresReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,
        [Parameter(Mandatory = $true)]
        [string]$PostgresUser,
        [Parameter(Mandatory = $true)]
        [string]$PostgresDb,
        [int]$TimeoutSeconds = 120,
        [int]$PollSeconds = 2
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = ''

    Write-Host "Waiting for PostgreSQL readiness in $ContainerName" -ForegroundColor Cyan

    while ((Get-Date) -lt $deadline) {
        $state = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $ContainerName 2>$null
        if ($state) {
            $currentState = ($state | Select-Object -First 1).ToString().Trim()
            if ($currentState -ne $lastState) {
                Write-Host "Container state: $currentState" -ForegroundColor DarkGray
                $lastState = $currentState
            }
        }

        docker exec $ContainerName sh -lc "pg_isready -U '$PostgresUser' -d '$PostgresDb'" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL is ready in $ContainerName" -ForegroundColor Green
            return
        }

        Start-Sleep -Seconds $PollSeconds
    }

    throw "Timed out waiting for PostgreSQL readiness in $ContainerName"
}

function Wait-ForHttpOk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [string]$ExpectedJsonStatus = '',
        [int]$TimeoutSeconds = 120,
        [int]$PollSeconds = 2
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    Write-Host "Waiting for HTTP readiness at $Url" -ForegroundColor Cyan

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                if (-not $ExpectedJsonStatus) {
                    Write-Host "HTTP endpoint is ready at $Url" -ForegroundColor Green
                    return
                }

                $payload = $response.Content | ConvertFrom-Json -ErrorAction Stop
                if ($payload.status -eq $ExpectedJsonStatus) {
                    Write-Host "HTTP endpoint is ready at $Url" -ForegroundColor Green
                    return
                }
            }
        }
        catch {
        }

        Start-Sleep -Seconds $PollSeconds
    }

    throw "Timed out waiting for HTTP readiness at $Url"
}

function Clear-KillSwitchIfNeeded {
    param(
        [Parameter(Mandatory = $true)]
        [int]$BackendPort,
        [Parameter(Mandatory = $true)]
        [string]$ApiPrefix,
        [switch]$KeepKillSwitchEnabled
    )

    if ($KeepKillSwitchEnabled) {
        Write-Host 'Leaving kill switch enabled by request.' -ForegroundColor Yellow
        return
    }

    $snapshotUrl = "http://localhost:$BackendPort$ApiPrefix/controls/snapshot"
    $toggleUrl = "http://localhost:$BackendPort$ApiPrefix/controls/kill-switch/toggle"

    try {
        $snapshot = Invoke-RestMethod -Uri $snapshotUrl -Method Get -TimeoutSec 10
        if (-not $snapshot.kill_switch_enabled) {
            Write-Host 'Kill switch is already disabled for startup.' -ForegroundColor DarkGray
            return
        }

        Write-Host 'Clearing persisted kill switch for startup...' -ForegroundColor Cyan
        $payload = @{ enabled = $false } | ConvertTo-Json
        $null = Invoke-RestMethod -Uri $toggleUrl -Method Post -ContentType 'application/json' -Body $payload -TimeoutSec 10
        Write-Host 'Kill switch disabled for startup.' -ForegroundColor Green
    }
    catch {
        throw "Backend is healthy, but kill switch reset failed: $($_.Exception.Message)"
    }
}

function Invoke-ControlAction {
    param(
        [Parameter(Mandatory = $true)]
        [int]$BackendPort,
        [Parameter(Mandatory = $true)]
        [string]$ApiPrefix,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [hashtable]$Payload,
        [string]$Label = $Path,
        [int]$TimeoutSeconds = 120
    )

    $uri = "http://localhost:$BackendPort$ApiPrefix$Path"
    $body = $Payload | ConvertTo-Json -Depth 6
    Write-Host "Startup action: $Label" -ForegroundColor Cyan
    $response = Invoke-RestMethod -Uri $uri -Method Post -ContentType 'application/json' -Body $body -TimeoutSec $TimeoutSeconds
    if ($null -ne $response.message) {
        Write-Host ("  {0}" -f $response.message) -ForegroundColor DarkGray
    }
    return $response
}

function Invoke-StartupPipeline {
    param(
        [Parameter(Mandatory = $true)]
        [int]$BackendPort,
        [Parameter(Mandatory = $true)]
        [string]$ApiPrefix
    )

    $allAssetsPayload = @{ asset_class = 'all'; force = $true }
    $universeOnlyPayload = @{ asset_class = 'all'; force = $true; cascade = $false }

    Invoke-ControlAction -BackendPort $BackendPort -ApiPrefix $ApiPrefix -Path '/controls/universe/run-once' -Payload $universeOnlyPayload -Label 'Universe refresh' | Out-Null
    Invoke-ControlAction -BackendPort $BackendPort -ApiPrefix $ApiPrefix -Path '/controls/candles/backfill' -Payload $allAssetsPayload -Label 'Candle backfill' -TimeoutSeconds 300 | Out-Null
    Invoke-ControlAction -BackendPort $BackendPort -ApiPrefix $ApiPrefix -Path '/controls/regime/run-once' -Payload $allAssetsPayload -Label 'Regime recompute' | Out-Null
    Invoke-ControlAction -BackendPort $BackendPort -ApiPrefix $ApiPrefix -Path '/controls/strategy/run-once' -Payload $allAssetsPayload -Label 'Strategy refresh' | Out-Null
}

function Invoke-LocalAlembic {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    Write-Host 'Running Alembic locally against localhost DB mapping...' -ForegroundColor DarkGray

    Push-Location (Join-Path $RepoRoot 'backend')
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Alembic exited with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

$script:WtTabQueue = New-Object System.Collections.Generic.List[string]

function Add-WtTab {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string]$PowerShellExe
    )

    $safeTitle = $Title.Replace('"', '\"')
    $safeWd = $WorkingDirectory.Replace('"', '\"')
    $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($Command))

    $tab = @(
        'new-tab'
        "--title `"$safeTitle`""
        "--startingDirectory `"$safeWd`""
        $PowerShellExe
        '-NoExit'
        '-EncodedCommand'
        $encodedCommand
    ) -join ' '

    $script:WtTabQueue.Add($tab) | Out-Null
}

function Start-WtTabs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $wt = Get-Command 'wt.exe' -ErrorAction SilentlyContinue
    if (-not $wt) {
        Write-Warning 'Windows Terminal (wt.exe) was not found. Skipping log tabs.'
        return
    }

    if ($script:WtTabQueue.Count -eq 0) {
        return
    }

    $joinedTabs = $script:WtTabQueue -join ' ; '
    Start-Process -FilePath $wt.Source -ArgumentList "-w 0 $joinedTabs" -WorkingDirectory $RepoRoot | Out-Null
}

function Queue-LogTabs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$PowerShellExe,
        [Parameter(Mandatory = $true)]
        [int]$BackendPort,
        [Parameter(Mandatory = $true)]
        [string]$ApiPrefix,
        [switch]$NoFrontendLogs
    )

    $backendLogCommand = @"
Set-Location "$RepoRoot"
Write-Host "Trade_Bot backend logs" -ForegroundColor Cyan
docker compose logs -f backend
"@
    Add-WtTab -Title 'Trade_Bot - Backend Logs' -WorkingDirectory $RepoRoot -Command $backendLogCommand -PowerShellExe $PowerShellExe

    $workerPattern = '(universe|candle|feature|regime|strategy|risk|execution|stop|position|workflow|kill_switch|flatten|control\.)'
    $workerLogCommand = @"
Set-Location "$RepoRoot"
Write-Host "Trade_Bot worker stream" -ForegroundColor Cyan
docker compose logs -f backend | Select-String -Pattern '$workerPattern'
"@
    Add-WtTab -Title 'Trade_Bot - Worker Stream' -WorkingDirectory $RepoRoot -Command $workerLogCommand -PowerShellExe $PowerShellExe

    if (-not $NoFrontendLogs) {
        $frontendLogCommand = @"
Set-Location "$RepoRoot"
Write-Host "Trade_Bot frontend logs" -ForegroundColor Cyan
docker compose logs -f frontend
"@
        Add-WtTab -Title 'Trade_Bot - Frontend Logs' -WorkingDirectory $RepoRoot -Command $frontendLogCommand -PowerShellExe $PowerShellExe
    }

    $postgresLogCommand = @"
Set-Location "$RepoRoot"
Write-Host "Trade_Bot postgres logs" -ForegroundColor Cyan
docker compose logs -f postgres
"@
    Add-WtTab -Title 'Trade_Bot - Postgres Logs' -WorkingDirectory $RepoRoot -Command $postgresLogCommand -PowerShellExe $PowerShellExe

    $systemEventCommand = @"
Set-Location "$RepoRoot"
`$apiUrl = "http://localhost:$BackendPort$ApiPrefix/system-events?limit=25"
`$seen = @{}
Write-Host "Polling Trade_Bot system events from `$apiUrl" -ForegroundColor Cyan

while (`$true) {
    try {
        `$events = Invoke-RestMethod -Uri `$apiUrl -Method Get -TimeoutSec 5
        if (`$events) {
            foreach (`$event in @(`$events | Sort-Object created_at)) {
                `$fingerprint = "{0}|{1}|{2}|{3}" -f `$event.created_at, `$event.event_type, `$event.severity, `$event.message
                if (-not `$seen.ContainsKey(`$fingerprint)) {
                    Write-Host ("[{0}] {1} {2} {3}" -f `$event.created_at, `$event.severity.ToUpper(), `$event.event_type, `$event.message)
                    if (`$event.payload) {
                        Write-Host ("  payload: {0}" -f ((`$event.payload | ConvertTo-Json -Compress -Depth 6))) -ForegroundColor DarkGray
                    }
                    `$seen[`$fingerprint] = `$true
                }
            }
        }
    }
    catch {
        Write-Host ("event poll retry: {0}" -f `$_.Exception.Message) -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 3
}
"@
    Add-WtTab -Title 'Trade_Bot - System Events' -WorkingDirectory $RepoRoot -Command $systemEventCommand -PowerShellExe $PowerShellExe
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Start-Bot.ps1 requires PowerShell 7 or newer.'
}

Assert-CommandAvailable -Name 'docker'
$null = docker info 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker daemon is not reachable. Start Docker Desktop first.'
}

$powerShellExe = if (Get-Command 'pwsh' -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
$pythonExe = Resolve-PythonExe -RepoRoot $repoRoot

$stateDir = Join-Path $repoRoot 'scripts/.runtime'
$statePath = Join-Path $stateDir 'bot-state.json'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$envMap = Get-EnvMap -Path (Join-Path $repoRoot '.env')
$backendPort = [int](Get-SettingValue -Map $envMap -Key 'BACKEND_PORT' -DefaultValue '8101')
$frontendPort = [int](Get-SettingValue -Map $envMap -Key 'FRONTEND_PORT' -DefaultValue '4174')
$apiPrefix = Get-SettingValue -Map $envMap -Key 'API_V1_PREFIX' -DefaultValue '/api/v1'
$defaultMode = Get-SettingValue -Map $envMap -Key 'DEFAULT_MODE' -DefaultValue 'mixed'
$stockMode = Get-SettingValue -Map $envMap -Key 'STOCK_EXECUTION_MODE' -DefaultValue 'paper'
$cryptoMode = Get-SettingValue -Map $envMap -Key 'CRYPTO_EXECUTION_MODE' -DefaultValue 'paper'
$postgresUser = Get-SettingValue -Map $envMap -Key 'POSTGRES_USER' -DefaultValue 'tradingbot'
$postgresDb = Get-SettingValue -Map $envMap -Key 'POSTGRES_DB' -DefaultValue 'tradingbot'

$requiredServices = @('postgres', 'backend')
if (-not $NoFrontend) {
    $requiredServices += 'frontend'
}

$allRunning = @($requiredServices | Where-Object { $_ -notin (Get-RunningServices) }).Count -eq 0

Write-Host ''
Write-Host '===== Trade_Bot Startup =====' -ForegroundColor Cyan
Write-Host "Repo root: $repoRoot"
Write-Host "Mode: mixed | Stock: $stockMode | Crypto: $cryptoMode"
Write-Host 'Worker order: universe -> candle -> feature -> regime -> strategy -> risk -> execution -> stop -> position'
Write-Host ''

if ($allRunning -and -not $Force) {
    Write-Host 'Trade_Bot stack is already running.' -ForegroundColor Yellow

    if (-not $NoLogTabs) {
        Queue-LogTabs -RepoRoot $repoRoot -PowerShellExe $powerShellExe -BackendPort $backendPort -ApiPrefix $apiPrefix -NoFrontendLogs:$NoFrontend
        Start-WtTabs -RepoRoot $repoRoot
    }

    $serviceStates = @()
    foreach ($serviceName in $requiredServices) {
        $info = Get-ContainerInfo -ServiceName $serviceName
        if ($null -ne $info) {
            $serviceStates += $info
        }
    }

    $state = [ordered]@{
        startedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
        repoRoot     = $repoRoot
        backendUrl   = "http://localhost:$backendPort"
        frontendUrl  = if ($NoFrontend) { $null } else { "http://localhost:$frontendPort" }
        mode         = [ordered]@{
            default = $defaultMode
            stock   = $stockMode
            crypto  = $cryptoMode
        }
        workerOrder  = @('universe', 'candle', 'feature', 'regime', 'strategy', 'risk', 'execution', 'stop', 'position')
        services     = $serviceStates
    }

    $state | ConvertTo-Json -Depth 6 | Set-Content -Path $statePath -Encoding UTF8
    docker compose ps
    exit 0
}

Write-Host '1/5 Starting PostgreSQL...' -ForegroundColor Cyan
docker compose up -d postgres | Out-Null
Wait-ForPostgresReady -ContainerName 'tradingbot_postgres' -PostgresUser $postgresUser -PostgresDb $postgresDb -TimeoutSeconds $PostgresTimeoutSeconds

if (-not $SkipMigrations) {
    Write-Host '2/5 Running Alembic migrations...' -ForegroundColor Cyan
    Invoke-LocalAlembic -RepoRoot $repoRoot -PythonExe $pythonExe
}
else {
    Write-Host '2/5 Skipping Alembic migrations by request.' -ForegroundColor Yellow
}

Write-Host '3/5 Starting backend...' -ForegroundColor Cyan
docker compose up -d backend | Out-Null
Wait-ForHttpOk -Url "http://localhost:$backendPort/health" -ExpectedJsonStatus 'ok' -TimeoutSeconds $BackendTimeoutSeconds
Clear-KillSwitchIfNeeded -BackendPort $backendPort -ApiPrefix $apiPrefix -KeepKillSwitchEnabled:$KeepKillSwitchEnabled
Write-Host '3.5/5 Priming startup pipeline...' -ForegroundColor Cyan
Invoke-StartupPipeline -BackendPort $backendPort -ApiPrefix $apiPrefix

if (-not $NoFrontend) {
    Write-Host '4/5 Starting frontend...' -ForegroundColor Cyan
    docker compose up -d frontend | Out-Null
    Wait-ForHttpOk -Url "http://localhost:$frontendPort" -TimeoutSeconds $FrontendTimeoutSeconds
}
else {
    Write-Host '4/5 Frontend skipped by request.' -ForegroundColor Yellow
}

Write-Host '5/5 Capturing runtime state...' -ForegroundColor Cyan
$serviceStates = @()
foreach ($serviceName in $requiredServices) {
    $info = Get-ContainerInfo -ServiceName $serviceName
    if ($null -ne $info) {
        $serviceStates += $info
    }
}

$state = [ordered]@{
    startedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    repoRoot     = $repoRoot
    backendUrl   = "http://localhost:$backendPort"
    frontendUrl  = if ($NoFrontend) { $null } else { "http://localhost:$frontendPort" }
    mode         = [ordered]@{
        default = $defaultMode
        stock   = $stockMode
        crypto  = $cryptoMode
    }
    workerOrder  = @('universe', 'candle', 'feature', 'regime', 'strategy', 'risk', 'execution', 'stop', 'position')
    services     = $serviceStates
}

$state | ConvertTo-Json -Depth 6 | Set-Content -Path $statePath -Encoding UTF8

if (-not $NoLogTabs) {
    Queue-LogTabs -RepoRoot $repoRoot -PowerShellExe $powerShellExe -BackendPort $backendPort -ApiPrefix $apiPrefix -NoFrontendLogs:$NoFrontend
    Start-WtTabs -RepoRoot $repoRoot
}

Write-Host ''
Write-Host 'Trade_Bot stack is up.' -ForegroundColor Green
Write-Host "Backend:  http://localhost:$backendPort"
if (-not $NoFrontend) {
    Write-Host "Frontend: http://localhost:$frontendPort"
}
Write-Host "State:    $statePath"
Write-Host ''
docker compose ps