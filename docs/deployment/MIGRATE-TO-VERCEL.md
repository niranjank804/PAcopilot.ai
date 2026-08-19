# Migrating from Render to Vercel

Status: **step 1 (database) ready to run. Steps 2–5 in progress.**

## What goes where

Vercel does not host Postgres. The database moves to **Neon**, which is
what the Vercel Marketplace provisions, so it is still managed from the
Vercel dashboard and billed through Vercel.

| Piece | From | To |
|---|---|---|
| Frontend | Render (still running) | Vercel — **done** |
| Backend (FastAPI) | Render web service | Vercel Python Functions |
| Postgres | Render | Neon (via Vercel Marketplace) |
| Scheduler | in-process loop | opportunistic + daily cron |
| Rate limiting | in-process | Upstash Redis |
| Artifacts / uploads | through the API | presigned S3 URLs |

## What Vercel gives you that Render's free tier does not

Worth stating, because it is the reason this is an upgrade rather than a
lateral move:

- **2 GB memory / 1 vCPU** per function on Hobby, against Render free's
  512 MB. Visual RAG rasterization has real headroom for the first time.
- **300s maximum duration** on Hobby. Long AI tool loops stop being a
  gamble.
- **No 15-minute spin-down.** The 30–60s cold start that made the first
  request after a quiet period look like an outage goes away.
- FastAPI is a first-class preset, auto-detected from `requirements.txt`,
  and Python 3.14 (what this project runs) is supported.

## What breaks, and what it costs to fix

Serverless is not a container with a different bill. Four things in this
codebase depend on being a long-lived process:

### 1. Request and response bodies are capped at 4.5 MB

`MAX_UPLOAD_BYTES` is 50 MB and `MAX_ATTACHMENT_BYTES` is 15 MB. Report
artifacts — Excel workbooks — are served through the API too and
routinely exceed 4.5 MB.

**Fix:** presigned S3 URLs, so bytes never traverse the function. The
`S3StorageBackend` already exists and already does the tenant-prefix
check, so this is presigning plus a frontend change, not new
infrastructure.

### 2. Hobby cron runs once per day

Not "once per day by default" — a cron expression that would run more
often **fails at deployment**. The report reaper runs every 60s and
reclaims leases from workers that died mid-job.

**Fix:** reap opportunistically on the worker claim path. Workers poll
every ~2s while working, so expired leases get reclaimed exactly when
someone is looking for work — which is arguably better than a fixed
timer — with a daily cron as a backstop for a fully idle system.

### 3. The database pool multiplies by the instance count

Vercel autoscales. `DATABASE_POOL_SIZE=10` plus overflow, times however
many instances are warm, exhausts Postgres connections quickly.

**Fix:** already done. `src/database/url.py` detects Neon's pooled
endpoint and switches SQLAlchemy to `NullPool`, since pgbouncer is
already pooling. See step 1 below.

### 4. Rate limiting silently stops working

`src/core/rate_limit.py` keeps its windows in a module-level dict. On
serverless each instance counts separately, so the effective limit is
the configured one multiplied by the number of warm instances. It does
not error — it just stops limiting.

This is the one with a security consequence: those windows are what
stand between `/auth/login` and credential stuffing.

**Fix:** Upstash Redis (free tier, Vercel Marketplace) for shared
counters.

---

## Step 1 — database to Neon

The code side is done. `DATABASE_URL` is now accepted as a single
connection string, in addition to the five discrete `DATABASE_*`
settings, and `src/database/url.py` handles the parts of Neon's URL that
asyncpg cannot take:

- `sslmode` and `channel_binding` are **libpq** parameters. asyncpg is
  not built on libpq and rejects them; `sslmode` is translated to its
  own `ssl` argument and the rest are dropped. Alembic's URL keeps them,
  because psycopg2 *is* built on libpq and wants them.
- Neon's `-pooler` endpoint is pgbouncer in transaction mode, where
  prepared statements do not survive. All three SQLAlchemy-documented
  mitigations are applied automatically when a pooled host is detected:
  `prepared_statement_cache_size=0`, uuid statement names, and
  `NullPool`.

Getting those wrong produces an app that connects, serves traffic, and
then fails intermittently under concurrency — so it is covered by
`tests/unit/database/test_url.py`.

### 1a. Create the database

Vercel dashboard → **Storage** → **Create Database** → **Neon**. Free
tier. Pick the region nearest your users; `eu-central-1` matches the
existing S3 bucket in `eu-north-1` reasonably well.

Vercel injects `DATABASE_URL` into the project automatically. Copy the
**pooled** connection string (the one whose host contains `-pooler`) for
the application, and the **direct** one for migrations.

### 1b. Copy the data

From a machine with `pg_dump`/`psql` (both ship with Postgres):

```bash
# Render's connection string, from its dashboard.
pg_dump "<render-external-url>" \
  --no-owner --no-privileges --no-acl \
  -Fc -f pacopilot.dump

# Neon's DIRECT url, not the pooled one — restore issues DDL.
pg_restore --no-owner --no-privileges \
  -d "<neon-direct-url>" pacopilot.dump
```

`--no-owner`/`--no-privileges` matter: the Render role does not exist on
Neon, and without them every `ALTER ... OWNER TO` fails.

### 1c. Point the app at it and verify

Locally first, before touching the deployment:

```bash
# backend/.env
DATABASE_URL=<neon-pooled-url>
```

```bash
cd backend
python -m alembic current          # should report e9b3c7d21f45 (head)
python -m pytest -q                # full suite against Neon
```

The suite runs against whatever `DATABASE_*`/`DATABASE_URL` points at,
so a green run here is a genuine end-to-end check of the new database —
including the pooled endpoint, which is the part most likely to
misbehave.

### 1d. Cut over

Set `DATABASE_URL` on the Render backend to the Neon pooled URL and
redeploy. Render's own Postgres can then be deleted. Running the backend
on Render against Neon is a deliberate intermediate state: it proves the
database move in isolation, before the platform move adds its own
variables.

---

## Step 2 — rate limiting to Upstash

Not started. Requires an Upstash account (Vercel Marketplace → Upstash
Redis → free tier).

## Step 3 — presigned uploads and downloads

Not started. Removes the 4.5 MB ceiling as a blocker.

## Step 4 — scheduler to opportunistic reaping

Not started.

## Step 5 — backend to Vercel

Not started. Needs steps 2–4 first; deploying before them produces a
backend that works in testing and fails on large uploads, stuck report
jobs, and unlimited login attempts.

---

## Rollback

Until step 5, rollback is changing `DATABASE_URL` back to Render's and
redeploying. Keep the Render database until the Neon one has served
production traffic for a few days — a dump is a point-in-time copy, and
anything written to Render after it was taken is not in Neon.
