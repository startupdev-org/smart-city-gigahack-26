# Run as Administrator. Copies pgvector from project scripts\pgvector17 into PostgreSQL 17.

$ErrorActionPreference = "Stop"
$pg = "C:\Program Files\PostgreSQL\17"
$src = Join-Path $PSScriptRoot "pgvector17"

if (-not (Test-Path "$src\lib\vector.dll")) {
  throw "Missing $src\lib\vector.dll — extract vector.v0.8.6-pg17.zip into scripts\pgvector17 first"
}

Stop-Service postgresql-x64-17 -Force
Start-Sleep -Seconds 3
Copy-Item "$src\lib\vector.dll" "$pg\lib\vector.dll" -Force
Copy-Item "$src\share\extension\*" "$pg\share\extension\" -Force
New-Item -ItemType Directory -Force -Path "$pg\include\server\extension\vector" | Out-Null
Copy-Item "$src\include\server\extension\vector\*" "$pg\include\server\extension\vector\" -Force
Start-Service postgresql-x64-17
Start-Sleep -Seconds 3

$env:PGPASSWORD = "postgres"
& "$pg\bin\psql.exe" -U postgres -h localhost -d civic_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
& "$pg\bin\psql.exe" -U postgres -h localhost -d civic_ai -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
Write-Host "pgvector installed."
