#!/usr/bin/env bash
# Same blocking gates as `make ci`, for environments without make —
# notably Windows, where make is not installed by default.
#
#   bash scripts/ci.sh
#
# Kept in step with the Makefile by hand; both call the same commands the
# workflows call, which is what makes local green mean CI green.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

step "Lint (blocking rules)"
(cd "$BACKEND" && python -m ruff check src tests)

step "Migration integrity"
(cd "$BACKEND" && PYTHONPATH=. python scripts/check_migrations.py)

step "Test database"
# Same rule as the Makefile: the suite runs only against the docker-compose
# Postgres. A root .env may move its published port (POSTGRES_PORT).
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://postgres:postgres@localhost:${POSTGRES_PORT:-5432}/enterprise_ai_test}"
export TEST_DATABASE_URL
(cd "$ROOT" && docker compose up -d --wait postgres)
(cd "$BACKEND" && DATABASE_URL="$TEST_DATABASE_URL" PYTHONPATH=. python -m alembic upgrade head)
(cd "$BACKEND" && DATABASE_URL="$TEST_DATABASE_URL" PYTHONPATH=. python scripts/seed_roles.py)
(cd "$BACKEND" && DATABASE_URL="$TEST_DATABASE_URL" PYTHONPATH=. python scripts/seed_permissions.py)

step "Backend tests"
(cd "$BACKEND" && PYTHONPATH=. python -m pytest tests/unit tests/integration -q -p no:logging)

step "Dependency audit"
(cd "$BACKEND" && python -m pip_audit -r requirements.txt --strict \
  --ignore-vuln PYSEC-2026-1325)

step "Frontend typecheck, lint, test and build"
(cd "$FRONTEND" && npm run typecheck && npm run lint && npm run test && npm run build)

printf "\n\033[32mAll blocking gates passed.\033[0m\n"
