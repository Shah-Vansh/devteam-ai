<#
.SYNOPSIS
    One-time setup of DevTeam AI on Windows: checks tools, creates the Python virtual
    environment, installs backend and frontend dependencies, and creates .env.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -SkipFrontend
#>
param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }
function Stop-Setup($text) {
    Write-Host "`nSetup stopped: $text" -ForegroundColor Red
    exit 1
}

function Test-PythonCommand([string[]]$command) {
    # True if the command runs Python 3.12 or newer. Broken launcher entries just fail.
    try {
        $exe = $command[0]
        $prefix = @()
        if ($command.Length -gt 1) { $prefix = $command[1..($command.Length - 1)] }
        $out = & $exe @prefix -c "import sys; print(sys.version_info >= (3, 12))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "True")
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        @("py", "-3.14"), @("py", "-3.13"), @("py", "-3.12"), @("python"), @("python3")
    )
    foreach ($candidate in $candidates) {
        if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
            if (Test-PythonCommand $candidate) { return ,$candidate }
        }
    }
    return $null
}

# ---------- tools ----------
Write-Step "Checking tools"
$python = Find-Python
if ($null -eq $python) { Stop-Setup "Python 3.12 or newer is required (https://www.python.org/downloads/)." }
$pyExe = $python[0]
$pyArgs = @()
if ($python.Length -gt 1) { $pyArgs = $python[1..($python.Length - 1)] }
$version = & $pyExe @pyArgs -c "import platform; print(platform.python_version())"
Write-Ok "Python $version ($($python -join ' '))"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Stop-Setup "git is required (https://git-scm.com/downloads): generated projects are committed with it."
}
Write-Ok ((git --version) -join "")

if (-not $SkipFrontend) {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Stop-Setup "Node.js 22 or newer is required for the dashboard (https://nodejs.org), or run with -SkipFrontend."
    }
    $nodeVersion = (node --version).TrimStart("v")
    if ([int]($nodeVersion.Split(".")[0]) -lt 22) {
        Stop-Setup "Node.js 22 or newer is required (found $nodeVersion)."
    }
    Write-Ok "Node.js $nodeVersion"
}

# ---------- backend ----------
Write-Step "Python virtual environment (.venv)"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Write-Ok "already exists"
} else {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Stop-Setup "could not create .venv" }
    Write-Ok "created"
}

Write-Step "Backend dependencies (pip install -e backend[dev])"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e "backend[dev]"
if ($LASTEXITCODE -ne 0) { Stop-Setup "pip install failed" }
Write-Ok "installed"

# ---------- configuration ----------
Write-Step "Configuration (.env)"
if (Test-Path ".env") {
    Write-Ok "kept your existing .env"
} else {
    Copy-Item ".env.example" ".env"
    Write-Ok "created .env from .env.example"
}
$envText = Get-Content ".env" -Raw
$missing = @()
foreach ($key in @("LLM_API_KEY", "E2B_API_KEY")) {
    if ($envText -notmatch "(?m)^$key=\S+") { $missing += $key }
}
if ($missing.Count -gt 0) {
    Write-Warn ("Fill in " + ($missing -join " and ") + " in .env:")
    Write-Warn "  LLM_API_KEY  from https://console.groq.com/keys"
    Write-Warn "  E2B_API_KEY  from https://e2b.dev/dashboard (without it tests are reported NOT_EXECUTED)"
} else {
    Write-Ok "LLM_API_KEY and E2B_API_KEY are set"
}

# ---------- frontend ----------
if (-not $SkipFrontend) {
    Write-Step "Dashboard dependencies (npm ci)"
    Push-Location frontend
    try {
        npm ci --no-audit --no-fund --loglevel=error
        if ($LASTEXITCODE -ne 0) { Stop-Setup "npm ci failed" }
    } finally {
        Pop-Location
    }
    Write-Ok "installed"
}

# ---------- done ----------
Write-Step "Done"
Write-Host "    Start the API and the dashboard:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
Write-Host "    Run the backend tests:            cd backend; ..\.venv\Scripts\python.exe -m pytest"
Write-Host "    Plan, build and test from the CLI: cd backend; ..\.venv\Scripts\python.exe -m app.cli build ""Build a todo API"""
