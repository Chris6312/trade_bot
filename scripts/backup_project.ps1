<#
.SYNOPSIS
Creates a timestamped backup ZIP of the project including ONLY git tracked files.

.DESCRIPTION
- Uses `git ls-files` to gather the tracked files
- Preserves directory structure
- Outputs archive to /backups folder in project root
- Filename format: project_backup_YYYYMMDD_HHMMSS.zip

.USAGE
Run from anywhere inside the repo:

    pwsh .\scripts\backup-project.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "===== Trade_Bot Project Backup =====" -ForegroundColor Cyan

# Determine repo root
$repoRoot = git rev-parse --show-toplevel 2>$null
if (-not $repoRoot) {
    Write-Error "Not inside a Git repository."
    exit 1
}

Set-Location $repoRoot

# Timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Backup folder
$backupDir = Join-Path $repoRoot "backups"
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

# Archive name
$zipName = "Trade_Bot_backup_$timestamp.zip"
$zipPath = Join-Path $backupDir $zipName

Write-Host "Repo root: $repoRoot"
Write-Host "Backup file: $zipPath"

# Temporary staging folder
$tempDir = Join-Path $env:TEMP "gptbot_backup_$timestamp"
New-Item -ItemType Directory -Path $tempDir | Out-Null

Write-Host "Collecting git tracked files..."

# Get tracked files
$files = git ls-files

foreach ($file in $files) {

    $source = Join-Path $repoRoot $file
    $dest = Join-Path $tempDir $file

    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    if (Test-Path $source) {
		Copy-Item $source $dest -Force
	} else {
		Write-Warning "Skipping missing file: $source"
	}
}

Write-Host "Creating zip archive..."

Compress-Archive `
    -Path "$tempDir\*" `
    -DestinationPath $zipPath `
    -Force

# Cleanup temp
Remove-Item $tempDir -Recurse -Force

Write-Host ""
Write-Host "Backup completed successfully!" -ForegroundColor Green
Write-Host "Archive saved to:"
Write-Host $zipPath
Write-Host ""