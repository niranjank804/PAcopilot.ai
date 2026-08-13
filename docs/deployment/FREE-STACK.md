# Running PA-Copilot for free

Written after Render suspended the workspace for non-payment. Two facts
shaped this:

1. **Nothing in `render.yaml` is billable.** Both web services and the
   database are declared `plan: free`. The invoice comes from one of the
   other services in that account — the workspace has 7, this project
   declares 3.
2. **RBI rules block Render from auto-charging Indian cards.** Render
   says so in the suspension banner. That makes any paid Render usage
   recur as a manual payment every cycle — an operational tax, not a
   one-off.

So the goal is a stack with **no invoice at all**, not a cheaper one.

## Recommended free stack

| Layer | Host | Free tier | Card needed |
|---|---|---|---|
| Frontend (Next.js) | **Vercel** Hobby | generous; native Next.js | no |
| Backend (FastAPI) | **Render** free web service | 750 instance-h/month | no |
| Database (Postgres) | **Neon** or **Supabase** free | 0.5 GB, no expiry | no |

### Why move the database off Render

**Render's free Postgres is deleted after 90 days.** That is not a
spin-down — the data goes. Neon and Supabase free tiers have no such
expiry. You already use Supabase on another project, so that account
exists.

### Why move the frontend off Render

750 free instance-hours is 31.25 days, and a month is up to 744 hours.
**One** service fits comfortably; two do not. Moving the frontend to
Vercel leaves the backend alone inside the allowance permanently — and
Vercel runs Next.js natively, including the one dynamic route
(`/connections/[id]`) that would otherwise block a static export.

## Step 1 — clear the suspension

Unavoidable: Render will not restore until the outstanding invoice is
paid. Downgrading does not erase debt already incurred.

Then find what is actually billable — `render.yaml` is not it:

1. Render dashboard → **All (7)** services.
2. Look for any service not on a free plan, and any **paid Postgres**.
3. Delete or downgrade whatever you are not using.

## Step 2 — frontend to Vercel — DONE

**Live at https://pa-copilot-frontend.vercel.app**

Deployed via the Vercel CLI rather than the web UI, because the browser
flow landed on Vercel's *clone* screen ("Cloning from GitHub" with a
"Private Repository Name" field), which creates a duplicate repository
instead of importing the existing one — and offers no Root Directory
setting, which this monorepo needs.

Reproduce or redeploy with:

```bash
cd frontend
npx vercel link --yes --project pa-copilot-frontend
echo "https://pa-copilot-backend.onrender.com" | npx vercel env add NEXT_PUBLIC_API_URL production
npx vercel --prod --yes
```

Note the deployment-specific URL (`...-lsj8vjnyp-...vercel.app`) returns
302 — Vercel's deployment protection covers those. The clean project
alias above is the public one.

### Original UI instructions

Zero code changes. Next.js is Vercel's own framework.

1. vercel.com → **Add New → Project** → import `PAcopilot.ai`.
2. Set **Root Directory** to `frontend`.
3. Framework preset: Next.js (auto-detected). Leave build settings alone.
4. Add one environment variable:

   ```
   NEXT_PUBLIC_API_URL = https://pa-copilot-backend.onrender.com
   ```

5. Deploy. You get a `*.vercel.app` URL.

Then update the backend so the new origin can call it:

```
CORS_ALLOWED_ORIGINS = ["https://<your-app>.vercel.app"]
FRONTEND_URL         = https://<your-app>.vercel.app
```

`FRONTEND_URL` matters beyond CORS — password-reset emails build their
links from it.

Finally, delete the `pa-copilot-frontend` service on Render so it stops
consuming the allowance.

## Step 3 — database to Neon (or Supabase)

1. Create a free Postgres project; copy the connection string.
2. On the Render backend service, set `DATABASE_HOST`, `DATABASE_PORT`,
   `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` from it.
   Remove the `fromDatabase` blocks in `render.yaml` if you keep using
   the blueprint.
3. Migrations run themselves — the build command already ends with
   `alembic upgrade head` plus the seed scripts.

**Migrating existing data**, if there is any worth keeping:

```bash
pg_dump "<old-render-url>" --no-owner --no-privileges -f backup.sql
psql "<new-neon-url>" -f backup.sql
```

## What you lose on free tiers

Worth knowing before relying on it:

- **The backend spins down after ~15 minutes idle.** First request after
  that takes 30–60s. Once a PAfE worker is enrolled, its first heartbeat
  after a quiet period will look like an outage and recover on retry.
- **Free Postgres is small** (~0.5 GB). Report artifacts currently live
  in Postgres, which would consume it quickly — this is exactly why the
  S3 backend was built. Set `S3_BUCKET=pacopilot-s3` and artifacts move
  to S3's free tier (5 GB for 12 months) instead.
- **No SLA.** Fine for a preview; not for a paying customer.

## If you later want no spin-down

The cheapest way off spin-down is one paid backend instance (~$7/month).
Given the RBI auto-charge problem, prefer a provider that bills in a way
that works for you, or keep a calendar reminder to pay Render manually.

That is a decision to make when a real customer needs it — not before.
