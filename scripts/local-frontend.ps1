# The local website on http://localhost:3000 (started by run-local.ps1).
$Repo = Split-Path -Parent $PSScriptRoot
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
Set-Location (Join-Path $Repo "frontend")
Write-Host "PA-Copilot website (local) - http://localhost:3000   Close this window to stop." -ForegroundColor Cyan
npm run dev
