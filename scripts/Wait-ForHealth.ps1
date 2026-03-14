#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Http', 'DockerHealth', 'PostgresReady')]
    [string]$Mode,

    [string]$Url,
    [string]$ContainerName,
    [string]$ExpectedJsonStatus = '',
    [string]$PostgresUser = '',
    [string]$PostgresDb = '',
    [int]$TimeoutSeconds = 120,
    [int]$PollSeconds = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-HttpHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetUrl,
        [string]$ExpectedStatusValue
    )

    $response = Invoke-WebRequest -Uri $TargetUrl -Method Get -TimeoutSec 5
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
        return $null
    }

    $payload = $null
    if ($response.Content) {
        try {
            $payload = $response.Content | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            $payload = $null
        }
    }

    if ($ExpectedStatusValue) {
        if ($null -eq $payload) {
            return $null
        }

        if ($payload.PSObject.Properties.Name -contains 'status' -and $payload.status -eq $ExpectedStatusValue) {
            return [pscustomobject]@{
                mode       = 'Http'
                url        = $TargetUrl
                statusCode = $response.StatusCode
                payload    = $payload
            }
        }

        return $null
    }

    return [pscustomobject]@{
        mode       = 'Http'
        url        = $TargetUrl
        statusCode = $response.StatusCode
        payload    = $payload
    }
}

function Get-DockerContainerState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetContainerName
    )

    $status = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $TargetContainerName 2>$null
    if (-not $status) {
        return $null
    }

    return ($status | Select-Object -First 1).ToString().Trim()
}

function Test-DockerHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetContainerName
    )

    $normalized = Get-DockerContainerState -TargetContainerName $TargetContainerName
    if (-not $normalized) {
        return $null
    }

    if ($normalized -in @('healthy', 'running')) {
        return [pscustomobject]@{
            mode          = 'DockerHealth'
            containerName = $TargetContainerName
            status        = $normalized
        }
    }

    return $null
}

function Test-PostgresReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetContainerName,
        [Parameter(Mandatory = $true)]
        [string]$TargetPostgresUser,
        [Parameter(Mandatory = $true)]
        [string]$TargetPostgresDb
    )

    $probeOutput = docker exec $TargetContainerName sh -lc "pg_isready -U '$TargetPostgresUser' -d '$TargetPostgresDb'" 2>&1
    if ($LASTEXITCODE -eq 0) {
        return [pscustomobject]@{
            mode          = 'PostgresReady'
            containerName = $TargetContainerName
            postgresUser  = $TargetPostgresUser
            postgresDb    = $TargetPostgresDb
            probe         = ($probeOutput | Out-String).Trim()
        }
    }

    return $null
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

switch ($Mode) {
    'Http' {
        if (-not $Url) {
            throw 'Url is required when Mode is Http.'
        }

        Write-Host "Waiting for HTTP health at $Url" -ForegroundColor Cyan
        while ((Get-Date) -lt $deadline) {
            try {
                $result = Test-HttpHealth -TargetUrl $Url -ExpectedStatusValue $ExpectedJsonStatus
                if ($null -ne $result) {
                    Write-Host "HTTP health is ready at $Url" -ForegroundColor Green
                    $result
                    exit 0
                }
            }
            catch {
            }

            Start-Sleep -Seconds $PollSeconds
        }

        throw "Timed out waiting for HTTP health at $Url"
    }

    'DockerHealth' {
        if (-not $ContainerName) {
            throw 'ContainerName is required when Mode is DockerHealth.'
        }

        $lastStatus = ''
        Write-Host "Waiting for Docker health on $ContainerName" -ForegroundColor Cyan

        while ((Get-Date) -lt $deadline) {
            try {
                $currentStatus = Get-DockerContainerState -TargetContainerName $ContainerName
                if ($currentStatus -and $currentStatus -ne $lastStatus) {
                    Write-Host "Container state: $currentStatus" -ForegroundColor DarkGray
                    $lastStatus = $currentStatus
                }

                $result = Test-DockerHealth -TargetContainerName $ContainerName
                if ($null -ne $result) {
                    Write-Host "Docker container $ContainerName is $($result.status)." -ForegroundColor Green
                    $result
                    exit 0
                }
            }
            catch {
            }

            Start-Sleep -Seconds $PollSeconds
        }

        throw "Timed out waiting for Docker health on $ContainerName"
    }

    'PostgresReady' {
        if (-not $ContainerName) {
            throw 'ContainerName is required when Mode is PostgresReady.'
        }

        if (-not $PostgresUser) {
            throw 'PostgresUser is required when Mode is PostgresReady.'
        }

        if (-not $PostgresDb) {
            throw 'PostgresDb is required when Mode is PostgresReady.'
        }

        $lastStatus = ''
        Write-Host "Waiting for PostgreSQL readiness in $ContainerName" -ForegroundColor Cyan

        while ((Get-Date) -lt $deadline) {
            try {
                $currentStatus = Get-DockerContainerState -TargetContainerName $ContainerName
                if ($currentStatus -and $currentStatus -ne $lastStatus) {
                    Write-Host "Container state: $currentStatus" -ForegroundColor DarkGray
                    $lastStatus = $currentStatus
                }

                $result = Test-PostgresReady -TargetContainerName $ContainerName -TargetPostgresUser $PostgresUser -TargetPostgresDb $PostgresDb
                if ($null -ne $result) {
                    Write-Host "PostgreSQL is ready in $ContainerName" -ForegroundColor Green
                    $result
                    exit 0
                }
            }
            catch {
            }

            Start-Sleep -Seconds $PollSeconds
        }

        throw "Timed out waiting for PostgreSQL readiness in $ContainerName"
    }
}