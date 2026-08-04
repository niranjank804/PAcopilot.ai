# Reproduce CI locally. Every target below runs the same command the
# workflow runs, so "green here" and "green there" mean the same thing.
#
# `make ci` is the whole blocking gate set. If it passes, the pipeline
# should pass — the remaining difference is the runner OS.
#
# Windows: make is not installed by default. Either use `scripts/ci.sh`
# (Git Bash, same commands) or install make via winget/choco/scoop.

BACKEND  := backend
FRONTEND := frontend
PY       := python

.DEFAULT_GOAL := help
.PHONY: help install test lint typecheck coverage quality migrations audit \
        frontend-check ci clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd $(BACKEND) && $(PY) -m pip install -r requirements.txt -r requirements-dev.txt
	cd $(FRONTEND) && npm ci

test: ## Backend tests
	cd $(BACKEND) && PYTHONPATH=. $(PY) -m pytest tests/unit tests/integration -q -p no:logging

lint: ## Blocking lint (pyflakes-level only, same as CI)
	cd $(BACKEND) && $(PY) -m ruff check src tests

typecheck: ## Advisory type check — never blocks
	-cd $(BACKEND) && $(PY) -m mypy src

coverage: ## Backend tests with coverage
	cd $(BACKEND) && PYTHONPATH=. $(PY) -m pytest tests/unit tests/integration \
	  -q -p no:logging --cov=src --cov-report=term-missing --cov-report=xml

quality: coverage ## Coverage + lint trend report
	cd $(BACKEND) && PYTHONPATH=. $(PY) scripts/quality_report.py

migrations: ## Migration head and model-drift checks
	cd $(BACKEND) && PYTHONPATH=. $(PY) scripts/check_migrations.py

audit: ## Dependency vulnerability scan (same exceptions as CI)
	cd $(BACKEND) && $(PY) -m pip_audit -r requirements.txt --strict \
	  --ignore-vuln PYSEC-2026-1325
	cd $(FRONTEND) && npm audit --audit-level=high

frontend-check: ## Frontend typecheck, lint, test and build
	cd $(FRONTEND) && npm run typecheck && npm run lint && npm run test && npm run build

ci: lint migrations test frontend-check audit ## Everything CI blocks on
	@echo ""
	@echo "All blocking gates passed."

clean: ## Remove build and test artefacts
	cd $(BACKEND) && rm -rf .pytest_cache .coverage coverage.xml htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
