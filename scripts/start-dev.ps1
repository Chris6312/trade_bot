$ErrorActionPreference = 'Stop'

Write-Host 'Starting PostgreSQL, backend, and frontend containers...' -ForegroundColor Cyan

docker compose up -d
