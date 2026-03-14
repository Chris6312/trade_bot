$ErrorActionPreference = 'Stop'

Write-Host 'Stopping project containers...' -ForegroundColor Yellow

docker compose down
