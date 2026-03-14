#Requires -Version 7.0

[CmdletBinding()]
param(
    [int]$DrainSeconds = 10,
    [switch]$KillDocker
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

function Test-ServiceRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $running = @(docker compose ps --status running --services 2>$null)
    return $ServiceName -in $running
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Stop-Bot.ps1 requires PowerShell 7 or newer.'
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Required command 'docker' was not found in PATH."
}

$dockerReachable = $true
$null = docker info 2>$null
if ($LASTEXITCODE -ne 0) {
    $dockerReachable = $false
}

$statePath = Join-Path $repoRoot 'scripts/.runtime/bot-state.json'
$envMap = Get-EnvMap -Path (Join-Path $repoRoot '.env')
$backendPort = [int](Get-SettingValue -Map $envMap -Key 'BACKEND_PORT' -DefaultValue '8101')
$apiPrefix = Get-SettingValue -Map $envMap -Key 'API_V1_PREFIX' -DefaultValue '/api/v1'
$killSwitchUrl = "http://localhost:$backendPort$apiPrefix/controls/kill-switch/toggle"

Write-Host ''
Write-Host '===== Trade_Bot Shutdown =====' -ForegroundColor Yellow
Write-Host "Repo root: $repoRoot"
Write-Host ''

if ($dockerReachable -and (Test-ServiceRunning -ServiceName 'backend')) {
    try {
        Write-Host '1/4 Engaging kill switch before shutdown...' -ForegroundColor Yellow
        $payload = @{ enabled = $true } | ConvertTo-Json
        $null = Invoke-RestMethod -Uri $killSwitchUrl -Method Post -ContentType 'application/json' -Body $payload -TimeoutSec 10
        Write-Host 'Kill switch engaged.' -ForegroundColor Green
    }
    catch {
        Write-Warning "Could not engage kill switch via $killSwitchUrl. Continuing with shutdown."
    }

    if ($DrainSeconds -gt 0) {
        Write-Host "Allowing $DrainSeconds second(s) for in-flight work to settle..." -ForegroundColor Yellow
        Start-Sleep -Seconds $DrainSeconds
    }
}
else {
    Write-Host '1/4 Backend is not running or Docker is unavailable. Skipping kill switch call.' -ForegroundColor Yellow
}

if ($dockerReachable -and (Test-ServiceRunning -ServiceName 'frontend')) {
    Write-Host '2/4 Stopping frontend container...' -ForegroundColor Yellow
    docker compose stop frontend | Out-Null
}
else {
    Write-Host '2/4 Frontend is not running. Skipping.' -ForegroundColor Yellow
}

if ($dockerReachable -and (Test-ServiceRunning -ServiceName 'backend')) {
    Write-Host '3/4 Stopping backend container...' -ForegroundColor Yellow
    docker compose stop backend | Out-Null
}
else {
    Write-Host '3/4 Backend is not running. Skipping.' -ForegroundColor Yellow
}

if ($dockerReachable) {
    Write-Host '4/4 Bringing compose stack down and removing orphan containers...' -ForegroundColor Yellow
    docker compose down --remove-orphans | Out-Null
}
else {
    Write-Warning 'Docker daemon is not reachable. Skipping compose shutdown.'
}

if (Test-Path $statePath) {
    Remove-Item $statePath -Force
}

if ($KillDocker) {
    Write-Host ''
    Write-Host 'Performing Docker Desktop / WSL cleanup...' -ForegroundColor Red

    foreach ($name in @('Docker Desktop', 'com.docker.backend', 'com.docker.build', 'com.docker.proxy', 'dockerd', 'wsl')) {
        @(Get-Process -Name $name -ErrorAction SilentlyContinue) |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }

    try {
        wsl --shutdown 2>$null
    }
    catch {
    }
}

Write-Host ''
Write-Host 'Trade_Bot stack is down.' -ForegroundColor Green
Write-Host 'Runtime state cleaned up.'