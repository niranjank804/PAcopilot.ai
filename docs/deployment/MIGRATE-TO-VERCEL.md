# Migrating from Render to Vercel

Status (2026-09-20): **database on Neon (done), frontend on Vercel (done),
backend code ready for Vercel (done, `cd03d1a` + `686c82d`), Vercel project
`pa-copilot-api` created — secrets and first deploy pending, then cutover.**

## Procedure from here

The code side is finished. What remains is configuration in the Vercel
dashboard and a cutover, in this order.

### 1. Add the secrets to the `pa-copilot-api` project

Settings → Environment Variables, all three environments. The non-secret
values are already set (`DEBUG`, `TENANCY_ENFORCEMENT_ENABLED`,
`SCHEDULER_ENABLED=false`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`,
`S3_BUCKET`, `S3_REGION`, `GOOGLE_OAUTH_CLIENT_ID`). Add:

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | Neon **pooled** string (host contains `-pooler`) | Runtime. `src/database/url.py` switches to NullPool for a pooler host. |
| `DATABASE_URL_UNPOOLED` | Neon **direct** string (the one Render uses) | Build only: Alembic and the seeds run over it. |
| `SECRET_KEY` | **same value as Render** | Existing sessions and refresh tokens stay valid. |
| `TM1_CREDENTIALS_KEY` | **same value as Render** | Stored TM1 credentials decrypt. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | same as Render | S3 artifacts and signed uploads. |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | same as Render | Models and embeddings. |
| `CRON_SECRET` | any long random string (`openssl rand -base64 32`) | Vercel sends it on cron calls; `/internal/cron/*` refuses without it. |
| `BOOTSTRAP_ADMIN_EMAIL`, `SMTP_*` | optional, same as Render | The admin already exists; the seed skips when unset. |

Then Deployments → Redeploy the latest. The build runs
`scripts/vercel_build.py` (migrations, seeds) and fails the deploy if the
database is unreachable — that is intentional.

### 2. Open the API to browsers

Settings → Deployment Protection → Vercel Authentication → **Preview only**
(the project was created with it on for all deployments, which returns a
login page to the frontend's requests).

### 3. Verify before pointing anything at it

```
curl https://pa-copilot-api.vercel.app/health/ready
```
must return `{"status":"ready", ...}` with the database check ok. Then
sign in through the frontend with `NEXT_PUBLIC_API_URL` temporarily
pointed at the new API on a preview deployment, or simply proceed to 4
and roll back by flipping the variable if anything fails.

### 4. S3 CORS (one rule, once)

The IAM key in use cannot edit bucket CORS, so in the S3 console for
`pacopilot-s3` → Permissions → CORS:

```json
[{"AllowedOrigins":["https://pa-copilot-frontend.vercel.app"],
  "AllowedMethods":["PUT","GET","HEAD"],"AllowedHeaders":["*"],
  "ExposeHeaders":["ETag"],"MaxAgeSeconds":3000}]
```
Until it exists, uploads fall back to the multipart path, which the
Vercel API rejects above 4.5 MB.

### 5. Cutover

On the **frontend** project set `NEXT_PUBLIC_API_URL` to
`https://pa-copilot-api.vercel.app` (all environments) and redeploy.
Google Sign-In needs no change: the OAuth origin is the frontend.
Keep Render running for a day; then delete the Render service, remove
`.github/workflows/keep-alive.yml`, and delete `render.yaml`.

### Rollback

Set `NEXT_PUBLIC_API_URL` back to the Render URL and redeploy the
frontend. Both backends share the same database and secrets, so either
serves the same data.


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
