<#
  Build pa-copilot-gateway.exe (one file, no Python needed on the target)
  and zip it into frontend\public\downloads, where the Gateways page links it.
  A zip, because browsers hold back a bare unsigned .exe as "unconfirmed".

      powershell -ExecutionPolicy Bypass -File .\gateway\build.ps1
#>

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Build = Join-Path $Here ".build"
$Venv = Join-Path $Build "venv"

if (-not (Test-Path $Venv)) {
    py -3.12 -m venv $Venv
}
& "$Venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install --quiet "requests==2.32.5" "pyinstaller==6.16.0"

Push-Location $Here
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --onefile --console `
    --name pa-copilot-gateway `
    --distpath (Join-Path $Build "dist") --workpath (Join-Path $Build "work") --specpath $Build `
    pa_gateway.py
Pop-Location

$Target = Join-Path (Split-Path -Parent $Here) "frontend\public\downloads"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Remove-Item (Join-Path $Target "pa-copilot-gateway.exe") -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Build "dist\pa-copilot-gateway.exe") `
    -DestinationPath (Join-Path $Target "pa-copilot-gateway.zip") -Force
Write-Host "Built $Target\pa-copilot-gateway.zip"
