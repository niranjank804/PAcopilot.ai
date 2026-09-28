<#
  Run PA-Copilot on this PC, to test TM1 servers on your own network.

  The hosted app (Vercel) cannot reach private addresses such as
  192.168.x.x — they exist only inside your network. A copy running here can.

  Isolated from production on purpose (settings in local-env.ps1):
    * its own database, pa_copilot_local, in the local Docker Postgres
      (backend\.env points at production Neon; that is overridden here)
    * no S3 — files are kept in the local database
    * private TM1 addresses allowed (TM1_ALLOW_PRIVATE_ADDRESSES)
  AI calls still use the keys in backend\.env, so they count against the
  same Anthropic/OpenAI accounts.

  Usage (from the repo root):
      powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
  Then sign in at http://localhost:3000 with the username and password it
  prints. Close the two server windows to stop.
#>

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }

Step "1/5 Starting the local database (Docker)"
Push-Location $Repo
cmd /c "docker compose up -d --wait postgres >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red; exit 1 }
Pop-Location
$exists = cmd /c "docker exec pa-copilot-postgres psql -U postgres -tAc ""SELECT 1 FROM pg_database WHERE datname='pa_copilot_local'"" 2>nul"
if (-not $exists) {
    cmd /c "docker exec pa-copilot-postgres psql -U postgres -qc ""CREATE DATABASE pa_copilot_local"" >nul 2>&1"
}
Write-Host "    ok"

. (Join-Path $PSScriptRoot "local-env.ps1")

Step "2/5 Preparing the local database (migrations and roles)"
Push-Location $Backend
cmd /c """$Python"" -m alembic upgrade head >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "Migrations failed." -ForegroundColor Red; Pop-Location; exit 1 }
cmd /c """$Python"" scripts\seed_roles.py >nul 2>&1"
cmd /c """$Python"" scripts\seed_permissions.py >nul 2>&1"
Write-Host "    ok"

Step "3/5 Local admin account"
& $Python scripts\local_admin.py
Pop-Location

Step "4/5 Starting the backend on http://localhost:8000 (new window)"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "local-backend.ps1")

Step "5/5 Starting the website on http://localhost:3000 (new window)"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "local-frontend.ps1")

Write-Host ""
Write-Host "Waiting for the backend..." -ForegroundColor Green
$ready = $false
foreach ($i in 1..30) {
    try { Invoke-RestMethod -TimeoutSec 3 "http://localhost:8000/health" | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { Write-Host "The backend did not start - look at its window for the error." -ForegroundColor Red; exit 1 }
Write-Host "Backend ready. Opening http://localhost:3000 ..." -ForegroundColor Green
Start-Sleep -Seconds 5
Start-Process "http://localhost:3000/login"
Write-Host "Sign in with the username and password shown above. In Connections, add your TM1 with its LAN address and its HTTPPortNumber." -ForegroundColor Green
