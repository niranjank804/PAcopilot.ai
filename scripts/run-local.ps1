<#
  Run PA-Copilot on this PC, to test TM1 servers on your own network.

  The hosted app (Vercel) cannot reach private addresses such as
  192.168.1.17 — they exist only inside your network. A copy running here can.

  Isolated from production on purpose:
    * its own database, pa_copilot_local, in the local Docker Postgres
      (backend\.env points at production Neon; that is overridden here)
    * no S3 — files are kept in the local database
    * private TM1 addresses allowed (TM1_ALLOW_PRIVATE_ADDRESSES)
  AI calls still use the keys in backend\.env, so they count against the
  same Anthropic/OpenAI accounts.

  Usage (from the repo root):
      powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
  Then open http://localhost:3000 and sign in with the username and
  password it prints. Close the two server windows to stop.
#>

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Frontend = Join-Path $Repo "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$LocalDb = "postgresql://postgres:postgres@localhost:5439/pa_copilot_local"

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }

Step "1/5 Starting the local database (Docker)"
Push-Location $Repo
cmd /c "docker compose up -d --wait postgres >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red; exit 1 }
Pop-Location
cmd /c "docker exec pa-copilot-postgres psql -U postgres -tAc ""SELECT 1 FROM pg_database WHERE datname='pa_copilot_local'"" > %TEMP%\pa_local_db.txt 2>nul"
if (-not (Get-Content "$env:TEMP\pa_local_db.txt" -ErrorAction SilentlyContinue)) {
    cmd /c "docker exec pa-copilot-postgres psql -U postgres -qc ""CREATE DATABASE pa_copilot_local"" >nul 2>&1"
}
Write-Host "    ok"

# Overrides for this session only; backend\.env still supplies the rest.
$env:DATABASE_URL = $LocalDb
$env:DATABASE_URL_UNPOOLED = ""
$env:S3_BUCKET = ""
$env:TM1_ALLOW_PRIVATE_ADDRESSES = "true"
$env:CORS_ALLOWED_ORIGINS = '["http://localhost:3000"]'
$env:FRONTEND_URL = "http://localhost:3000"
$env:REGISTRATION_AUTO_APPROVE = "true"
$env:UPSTASH_REDIS_REST_URL = ""
$env:UPSTASH_REDIS_REST_TOKEN = ""
$env:PYTHONPATH = "."

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
$backendCmd = "`$env:DATABASE_URL='$LocalDb'; `$env:DATABASE_URL_UNPOOLED=''; `$env:S3_BUCKET=''; " +
    "`$env:TM1_ALLOW_PRIVATE_ADDRESSES='true'; `$env:CORS_ALLOWED_ORIGINS='[""http://localhost:3000""]'; " +
    "`$env:FRONTEND_URL='http://localhost:3000'; `$env:REGISTRATION_AUTO_APPROVE='true'; " +
    "`$env:UPSTASH_REDIS_REST_URL=''; `$env:UPSTASH_REDIS_REST_TOKEN=''; `$env:PYTHONPATH='.'; " +
    "Set-Location '$Backend'; & '$Python' -m uvicorn src.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Step "5/5 Starting the website on http://localhost:3000 (new window)"
$frontendCmd = "`$env:NEXT_PUBLIC_API_URL='http://localhost:8000'; Set-Location '$Frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host ""
Write-Host "Opening http://localhost:3000 in about 20 seconds..." -ForegroundColor Green
Start-Sleep -Seconds 20
Start-Process "http://localhost:3000/login"
Write-Host "Sign in with the username and password shown above. In Connections, add your TM1 with its LAN address and its HTTPPortNumber." -ForegroundColor Green
