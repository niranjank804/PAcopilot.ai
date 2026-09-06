# Fixing the backend outage

The backend has been unreachable since around 19 August 2026. This is
what is wrong, what to do, and in what order.

## What is actually broken

`pa-copilot-backend.onrender.com` accepts a TCP connection, completes
the TLS handshake, and then returns nothing at all — on every route,
for over 75 seconds, repeatedly, for weeks.

The telling detail is that `/health` hangs too. It returns a literal
dictionary and touches no database, so a hang there means **no process
is answering**, not that a dependency is slow.

Two candidate causes, one of which the evidence rules out:

- **Instance hours exhausted.** Render suspends *all* free web services
  in a workspace when the 750 monthly hours run out. The Render frontend
  answers in ~1.3s, and it is a new calendar month, so this is not it.
- **The database is gone.** `render.yaml` populates `DATABASE_HOST` and
  friends via `fromDatabase: pa-copilot-db`. If that resource no longer
  exists those values resolve to nothing, `Settings()` fails validation,
  and the process dies during import — before it can serve `/health`.
  This fits every symptom.

**Free Render Postgres expires 30 days after creation, then has a
14-day grace period, after which Render deletes it and all its data.**

## Step 1 — find out whether the data still exists

This is the only step with a deadline, because it is the only loss that
cannot be undone.

Open the Render dashboard and look for the `pa-copilot-db` database.

| What you see | Meaning | Next |
|---|---|---|
| Present, active | Data is safe | Step 2 |
| Present, expiry warning | Recoverable, but not for long | Step 2, now |
| Not listed | Deleted; data is unrecoverable | Step 3 |

If it is present, copy its **External Database URL** (the one reachable
from outside Render — the internal one only resolves inside their
network).

## Step 2 — copy it somewhere permanent

First create the new database: Vercel dashboard → **Storage** → **Create
Database** → **Neon**, free tier. Neon's free tier does not expire.
Copy its connection string.

Then, from `backend/`:

```bash
python scripts/migrate_database.py
```

It asks for the two connection strings with the input hidden, copies
everything, and then **verifies the copy** — comparing row counts table
by table and checking the Alembic revision — before telling you it
worked. It also leaves `database-backup.dump` in the working directory,
because the dump is the only irreplaceable artifact in this process.

Connection strings are never passed as command-line arguments: those are
visible to other processes and persist in shell history.

If the source turns out to be unreachable, the script says which of the
three reasons it is — deleted, wrong credentials, or wrong host — since
they need different responses.

## Step 3 — if the data is gone

```bash
python scripts/migrate_database.py --fresh
```

Creates the schema at the current migration and seeds roles,
permissions and an admin user. The application will start and work;
previous conversations, connections and uploaded documents are gone and
nothing can bring them back.

## Step 4 — point the application at the new database

Set one variable on the Render backend service and redeploy:

```
DATABASE_URL = <the Neon POOLED connection string>
```

The pooled one — its host contains `-pooler`. The code handles what that
implies automatically (see `src/database/url.py`): Neon's URL carries
libpq parameters asyncpg rejects, and its pooled endpoint is pgbouncer
in transaction mode, where prepared statements do not survive.

`DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` and
`DATABASE_PASSWORD` can then be deleted from that service — a single
`DATABASE_URL` supersedes all five.

Verify locally before trusting it: put the same URL in `backend/.env`
and run `python -m pytest -q`. The suite runs against whatever is
configured, so a green run is a real end-to-end check of the new
database including the pooled endpoint.

## Step 5 — stop it happening again

**Delete the `pa-copilot-frontend` service on Render.** Two free web
services need about 1,488 instance-hours a month against an allowance of
750, so they exhaust the budget around mid-month and Render suspends
*both* — including the backend. The frontend is served by Vercel and
that Render copy does nothing except consume the allowance the backend
needs.

The free database problem is solved by the move itself: Neon's free tier
has no 30-day expiry.

## What was verified, and how

`scripts/migrate_database.py` was run end to end against a real
PostgreSQL 17 instance before being committed:

- **Copy path** — 31 tables, 2015 rows dumped, restored and verified
  identical, with the Alembic revision matching.
- **Fresh path** — produced 31 tables at the current revision with 5
  roles and 29 permissions seeded.
- **Failure paths** — a deleted database and a wrong password each
  produce the correct diagnosis rather than a stack trace.
- It runs from a directory with **no application configuration**, which
  an earlier version did not: it derived its table list by importing the
  models, which loads the app settings, so a database recovery tool
  required the application to be correctly configured. It now asks the
  database what tables it has.
