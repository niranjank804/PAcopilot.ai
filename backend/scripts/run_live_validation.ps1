<#
Live validation against a real TM1 DEV/test server, from this machine.

Run from the repository root:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\run_live_validation.ps1

What it asks, all at this console (the password is read masked, kept only in
this process's environment for the run, and removed afterwards; it is never
written to disk, the console history, or the evidence):

  1. Address, port, SSL, user, password.
  2. Write validation? Only if you type the server's name exactly, confirm
     the scope, and the target is listed in YOUR inventory of approved
     DEV/test servers (%USERPROFILE%\.pa-copilot\live-targets.json). The run
     never creates or edits that file.
  3. Consent to store the password, encrypted with a throwaway key, in the
     local TEST database for the duration of each test (rolled back after).
     Without it, tests that use PA-Copilot's own API are BLOCKED.
  4. Paid AI calls? Separate, off unless you type PAID.

Evidence (allowlisted fields only, no credentials, no raw output) goes to
docs\evidence\live\<run>\: run.json, manifest.json, results.json.
#>

$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $backend
Set-Location $backend

Write-Host ""
Write-Host "PA-Copilot live validation (TM1 DEV/test only)" -ForegroundColor Cyan
Write-Host "Credentials stay in this console's process; nothing is saved." -ForegroundColor DarkGray
Write-Host ""

$address = Read-Host "TM1 address (e.g. localhost)"
$port = Read-Host "TM1 HTTP port (HTTPPortNumber in tm1s.cfg)"
$ssl = Read-Host "Use SSL? (y/n)"
$user = Read-Host "TM1 user (native auth)"
$secure = Read-Host "TM1 password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

# --- Write validation: separate, explicit, bound to one target ------------
$write = $false
$inventory = Join-Path $env:USERPROFILE ".pa-copilot\live-targets.json"
$answer = Read-Host "Run WRITE validation on run-owned fixtures? (y/n)"
if ($answer -match '^(y|yes)$') {
    if (-not (Test-Path $inventory)) {
        Write-Host "No approved-target inventory at $inventory - write tests will be BLOCKED." -ForegroundColor Yellow
        Write-Host "Create it yourself, listing only DEV/test servers, e.g.:" -ForegroundColor Yellow
        Write-Host '  [{"address": "localhost", "port": 12354, "server_name": "Planning Sample", "purpose": "DEV sample"}]' -ForegroundColor Yellow
    }
    $server = Read-Host "Type the TM1 server's name exactly as TM1 reports it"
    Write-Host ""
    Write-Host "Scope: create, change and delete ONLY objects named zzPACopilotLive_<run>_*:" -ForegroundColor Yellow
    Write-Host "  up to 12 objects (processes, two dimensions, one cube), a few cells and" -ForegroundColor Yellow
    Write-Host "  rules of that cube, and two reviewed processes that touch nothing else." -ForegroundColor Yellow
    $scope = Read-Host "Confirm this scope on that server? (yes/no)"
    if ($server -and $scope -eq "yes") { $write = $true }
}

$consent = Read-Host "Store the password, encrypted with a throwaway key, in the local TEST database for each test (rolled back after)? (y/n)"
$ai = Read-Host "Make PAID AI calls too? Type PAID to allow, anything else to skip"

# --- Environment for this process only ------------------------------------
$env:TM1_ADDRESS = $address
$env:TM1_PORT = $port
$env:TM1_SSL = if ($ssl -match '^(y|yes|true)$') { "true" } else { "false" }
$env:TM1_USER = $user
$env:TM1_PASSWORD = $password
$env:TM1_ALLOW_PRIVATE_ADDRESSES = "true"
$env:TM1_REQUEST_TIMEOUT_SECONDS = "30"
$env:TM1_PROCESS_RUN_TIMEOUT_SECONDS = "60"
$env:LIVE_MAX_MINUTES = "15"
$env:SECRET_KEY = "live-validation-secret-key-not-used-elsewhere"
$env:DEBUG = "False"
$env:PYTHONPATH = "."
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
if ($write) {
    $env:TM1_LIVE_WRITE = "1"; $env:TM1_LIVE_WRITE_SERVER = $server; $env:LIVE_WRITE_SCOPE_CONFIRMED = "1"
}
if ($ai -eq "PAID") { $env:LIVE_AI = "1" }

$markers = "live and not live_ai"
if ($consent -match '^(y|yes)$') {
    $env:LIVE_CREDENTIAL_STORAGE_CONSENT = "1"
} else {
    # Tests that store the connection (PA-Copilot's own path) are BLOCKED without consent.
    Write-Host "No consent to store the password: tests through PA-Copilot's own path will be BLOCKED." -ForegroundColor Yellow
}
if ($ai -eq "PAID") { $markers = $markers -replace " and not live_ai", "" }

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$evidence = Join-Path $repo "docs\evidence\live\$stamp"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$env:LIVE_EVIDENCE_DIR = $evidence

$commit = (git -C $repo rev-parse --short HEAD) 2>$null
$dirty = @(git -C $repo status --porcelain 2>$null).Count
@{
    script = "backend/scripts/run_live_validation.ps1"
    command = "python -m pytest tests/live -m `"$markers`""
    commit = $commit
    uncommitted_paths = $dirty
    read = $true
    write_requested = $write
    credential_storage_consent = ($consent -match '^(y|yes)$')
    paid_ai = ($ai -eq "PAID")
    transport = "DIRECT"
} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $evidence "run.json")

Write-Host ""
Write-Host "Running... (a minute or two)" -ForegroundColor Cyan
try {
    # Console only: test output is not saved, so values it prints never reach the evidence.
    & .\.venv\Scripts\python.exe -m pytest tests/live -m "$markers" -q -p no:cacheprovider -rs --tb=no 2>&1 |
        ForEach-Object { $_.ToString().Replace($password, "********") }
} finally {
    foreach ($name in "TM1_PASSWORD", "TM1_USER", "TM1_ADDRESS", "TM1_PORT", "TM1_SSL", "TM1_LIVE_WRITE",
                      "TM1_LIVE_WRITE_SERVER", "LIVE_WRITE_SCOPE_CONFIRMED", "LIVE_AI", "TM1_ALLOW_PRIVATE_ADDRESSES",
                      "LIVE_CREDENTIAL_STORAGE_CONSENT",
                      "LIVE_EVIDENCE_DIR") {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $password = $null
    $secure.Dispose()
}

$resultsFile = Join-Path $evidence "results.json"
if (Test-Path $resultsFile) {
    $results = Get-Content -Raw $resultsFile | ConvertFrom-Json
    Write-Host ""
    Write-Host "Summary" -ForegroundColor Cyan
    $results | Group-Object outcome | ForEach-Object { Write-Host ("  {0,-8} {1}" -f $_.Name, $_.Count) }
    $reasons = $results | Where-Object { $_.reason } | Group-Object reason
    foreach ($r in $reasons) { Write-Host ("  {0} x {1}" -f $r.Count, $r.Name) -ForegroundColor Yellow }
}
Write-Host ""
Write-Host "Evidence: $evidence (run.json, manifest.json, results.json)" -ForegroundColor Green
Write-Host "Tell Claude 'done' to read it." -ForegroundColor Green
