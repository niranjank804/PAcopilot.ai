<#
  Settings for the local copy of PA-Copilot (see run-local.ps1).
  Dot-sourced, so they apply to the current PowerShell session only;
  backend\.env still supplies everything not overridden here.
#>

# Its own database in the local Docker Postgres — never production Neon.
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5439/pa_copilot_local"
$env:DATABASE_URL_UNPOOLED = ""
# Files stay in the local database instead of the production S3 bucket.
$env:S3_BUCKET = ""
# TM1 servers on your own network (192.168.x) are allowed here.
$env:TM1_ALLOW_PRIVATE_ADDRESSES = "true"
$env:CORS_ALLOWED_ORIGINS = '["http://localhost:3000"]'
$env:FRONTEND_URL = "http://localhost:3000"
$env:REGISTRATION_AUTO_APPROVE = "true"
# Rate limits per process; no shared store needed on one PC.
$env:UPSTASH_REDIS_REST_URL = ""
$env:UPSTASH_REDIS_REST_TOKEN = ""
# Quiet: backend\.env may turn on SQL echo for development.
$env:DEBUG = "false"
$env:PYTHONPATH = "."
