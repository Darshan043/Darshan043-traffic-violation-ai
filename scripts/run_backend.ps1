# Start Traffic AI FastAPI Backend on port 8000
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

Write-Host "Starting Traffic AI Backend at http://localhost:8000 ..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
