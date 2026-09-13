# PA-Copilot

An AI assistant for IBM Planning Analytics (TM1). It connects to your TM1
servers, reads cube, dimension, process and chore metadata, answers
questions about the model, and drafts TurboIntegrator processes, rules and
feeders in your organization's own house style — with every change to a
live server going through an explicit human approval step.

## What it does

| Area | Capability |
|---|---|
| **Model exploration** | Browse cubes, dimensions, processes and chores; trace dependency graphs between objects |
| **Querying** | Run MDX against a connected server and read results back |
| **Code generation** | Draft TI processes, rules and feeders, grounded in reference material from the knowledge base rather than generic TM1 templates |
| **Deployment** | Propose changes as drafts; apply, verify and roll back with a snapshot taken immediately before the write |
| **Knowledge base** | Upload PDFs, Word documents and text; retrieval-augmented answers over them, including visual/page-image search |
| **Reports** | Schedule and run Planning Analytics for Excel workbooks via an enrolled Windows worker |
| **Administration** | Organizations, users, roles and fine-grained permissions, with an audit log |

Every agent turn is scoped to one organization, and a server-side allowlist
bounds which tools each persona may call.

## Stack

- **Backend** — FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, PostgreSQL
- **Frontend** — Next.js (App Router), TypeScript, Tailwind v4, shadcn/ui
- **AI** — Anthropic Claude for reasoning and tool use; OpenAI for embeddings
- **TM1** — TM1py, wrapped in a retrying client with a circuit breaker
- **Worker** — a separate Windows service for Excel/PAfE report execution

## Running it locally

**Prerequisites:** Python 3.11 or 3.12 (what CI tests), Node 20+, and a PostgreSQL 14+ database.

```bash
# 1. Configuration
cp .env.example backend/.env        # then fill in SECRET_KEY at minimum

# 2. Backend
cd backend
python -m pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. python -m alembic upgrade head
PYTHONPATH=. python scripts/seed_roles.py
PYTHONPATH=. python scripts/seed_permissions.py
PYTHONPATH=. python -m uvicorn src.main:app --reload    # → localhost:8000

# 3. Frontend (second terminal)
cd frontend
npm ci
npm run dev                                              # → localhost:3000
```

With `DEBUG=true` the interactive API docs are served at
`localhost:8000/docs`. They are off in production.

## Tests and checks

`make ci` runs everything the pipeline blocks on. Individually:

```bash
make lint            # ruff over backend src and tests
make test            # backend unit + integration tests
make migrations      # single migration head, and no model/schema drift
make frontend-check  # typecheck, lint, vitest, next build
make audit           # dependency vulnerability scan
```

On Windows without `make`, `scripts/ci.sh` runs the same commands under Git
Bash.

The backend tests need a reachable PostgreSQL instance — they run against
real Postgres with per-test transaction rollback, not an in-memory stand-in.
Tests marked `live` additionally need a real TM1 server and are excluded
from the default run.

## Layout

```
backend/src/
  api/v1/         HTTP routes
  services/       business logic, permission and ownership checks
  repositories/   data access
  database/       models, session, org-scoping backstop
  ai/             orchestrator, providers, tools, persona prompts
  tm1/            TM1py client, metadata, deployment and approval workflow
  knowledge/      document loaders, chunking, embeddings, retrieval
  middleware/     request correlation ids, security headers
frontend/src/
  app/            App Router pages
  components/     UI components
  lib/            API client, auth context
worker/           Windows report-execution worker
docs/             architecture, security, deployment and audit notes
```

## Documentation

- [`docs/AUDIT.md`](docs/AUDIT.md) — verified architectural facts, kept current
- [`docs/security-and-permissions.md`](docs/security-and-permissions.md) — the authorization model
- [`docs/ai-features-development-guide.md`](docs/ai-features-development-guide.md) — adding tools and personas
- [`docs/production-deployment.md`](docs/production-deployment.md) — deploying behind HTTPS

## Security

Report anything you find privately rather than in a public issue. Never
commit `backend/.env`, database dumps, or TM1 credentials — `.gitignore`
covers the known paths, and `TM1_CREDENTIALS_KEY` is what makes stored TM1
passwords readable, so it belongs with your other secrets and backups.
