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

step "Backend tests"
(cd "$BACKEND" && PYTHONPATH=. python -m pytest tests/unit tests/integration -q -p no:logging)

step "Dependency audit"
(cd "$BACKEND" && python -m pip_audit -r requirements.txt --strict \
  --ignore-vuln PYSEC-2026-1325)

step "Frontend typecheck, lint, test and build"
(cd "$FRONTEND" && npm run typecheck && npm run lint && npm run test && npm run build)

printf "\n\033[32mAll blocking gates passed.\033[0m\n"
