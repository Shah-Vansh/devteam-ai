<#
.SYNOPSIS
    Start the DevTeam AI API (http://127.0.0.1:8000) and dashboard (http://localhost:5173),
    each in its own window, then open the dashboard. Close the windows to stop them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Run scripts\setup.ps1 first (.venv is missing)." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Host "Run scripts\setup.ps1 first (.env is missing)." -ForegroundColor Red
    exit 1
}

Write-Host "Starting the API on http://127.0.0.1:8000 ..."
Start-Process -FilePath $python -ArgumentList "-m", "app.api" `
    -WorkingDirectory (Join-Path $root "backend")

Write-Host "Starting the dashboard on http://localhost:5173 ..."
Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $root "frontend")

# The API starts its MCP servers and applies migrations first; give both a moment.
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null
        $ready = $true
    } catch { }
}
if ($ready) {
    Write-Host "API is up. Opening the dashboard." -ForegroundColor Green
} else {
    Write-Host "The API is still starting; check its window for errors." -ForegroundColor Yellow
}
Start-Process "http://localhost:5173"
