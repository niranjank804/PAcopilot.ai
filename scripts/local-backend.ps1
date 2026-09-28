# The local backend on http://localhost:8000 (started by run-local.ps1).
$Repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "local-env.ps1")
Set-Location (Join-Path $Repo "backend")
Write-Host "PA-Copilot backend (local) - http://localhost:8000   Close this window to stop." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m uvicorn src.main:app --port 8000
