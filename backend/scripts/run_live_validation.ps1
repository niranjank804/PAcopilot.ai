<#
Live validation against a real TM1 DEV server, from this machine.

Asks for the server details and the password at the prompt (the password is
read hidden and is never written to disk, the console history or the
report). Runs the read-only live tests and, if you confirm, the write-path
tests, which create and remove their own zzPACopilotLive_* objects only.

The report (test names and results, no credentials) is saved under
docs/evidence/live/ for the scorecard.

Run from the backend folder:
    powershell -ExecutionPolicy Bypass -File scripts\run_live_validation.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host ""
Write-Host "PA-Copilot live validation (TM1 DEV only)" -ForegroundColor Cyan
Write-Host "Credentials stay in this window; nothing is saved." -ForegroundColor DarkGray
Write-Host ""

$address = Read-Host "TM1 address (e.g. localhost or 192.168.1.20)"
$port = Read-Host "TM1 HTTP port (the server's HTTPPortNumber, e.g. 8010)"
$ssl = Read-Host "Use SSL? (y/n)"
$user = Read-Host "TM1 user (native auth)"
$secure = Read-Host "TM1 password" -AsSecureString
$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

$env:TM1_ADDRESS = $address
$env:TM1_PORT = $port
$env:TM1_SSL = if ($ssl -match '^(y|yes|true)$') { "true" } else { "false" }
$env:TM1_USER = $user
$env:TM1_PASSWORD = $password
# A local DEV server has a private address; allow it for this run only.
$env:TM1_ALLOW_PRIVATE_ADDRESSES = "true"
$env:SECRET_KEY = "live-validation-secret-key-not-used-elsewhere"
$env:DEBUG = "False"
$env:PYTHONPATH = "."
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "The write-path tests create and delete their own zzPACopilotLive_* process," -ForegroundColor Yellow
Write-Host "dimensions and cube on this server. Run them only against DEV." -ForegroundColor Yellow
$server = Read-Host "To include them, type the TM1 server's name exactly (Enter to skip)"
if ($server) {
    $env:TM1_LIVE_WRITE = "1"
    $env:TM1_LIVE_WRITE_SERVER = $server
} else {
    Remove-Item Env:TM1_LIVE_WRITE -ErrorAction SilentlyContinue
    Remove-Item Env:TM1_LIVE_WRITE_SERVER -ErrorAction SilentlyContinue
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$reportDir = Join-Path (Split-Path -Parent (Get-Location)) "docs\evidence\live"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$report = Join-Path $reportDir "live-run-$stamp.txt"

Write-Host ""
Write-Host "Running... (a minute or two)" -ForegroundColor Cyan
try {
    & .\.venv\Scripts\python.exe -m pytest tests/live -m live -v -p no:cacheprovider -rs 2>&1 |
        ForEach-Object { $_.ToString().Replace($password, "********") } |
        Tee-Object -FilePath $report
} finally {
    foreach ($name in "TM1_PASSWORD", "TM1_USER", "TM1_ADDRESS", "TM1_PORT", "TM1_SSL",
                      "TM1_LIVE_WRITE", "TM1_LIVE_WRITE_SERVER", "TM1_ALLOW_PRIVATE_ADDRESSES") {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $password = $null
}

Write-Host ""
Write-Host "Report saved: $report" -ForegroundColor Green
Write-Host "It holds test names and results only. Tell Claude 'done' to read it." -ForegroundColor Green
