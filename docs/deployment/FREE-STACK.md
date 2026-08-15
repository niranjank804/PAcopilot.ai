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

### Root Directory must be set on the PROJECT, not just the CLI

`vercel link` from inside `frontend/` records the directory locally in
`.vercel/`, and `vercel --prod` from there uploads that directory, so CLI
deploys work. **Git-triggered builds do not use it.** They clone the
repository root and run `next build` there, which fails immediately:

```
Error: Couldn't find any `pages` or `app` directory.
      Please create one under the project root
```

Four consecutive pushes failed this way in 6-7 seconds each while the
alias kept serving a two-day-old build — green site, stale code, and no
signal anywhere except the Vercel deployment list.

**Fixed.** `rootDirectory` was `null` on the project and is now
`frontend`. There is no CLI flag for it, but it is a project field on the
REST API, which the CLI's own token can reach:

```bash
curl -X PATCH "https://api.vercel.com/v9/projects/$PROJECT_ID?teamId=$TEAM_ID"   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d '{"rootDirectory": "frontend"}'
```

`$PROJECT_ID` and `$TEAM_ID` are in `frontend/.vercel/project.json`; the
token is in the CLI's `auth.json`. Verify with a GET on the same URL —
`rootDirectory` should read `"frontend"`, not `null`.

Worth knowing for next time: the dashboard is not the only way to change
a project setting, and a setting that only exists in `.vercel/` locally
is not a setting the platform knows about.

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

## Step 4 — artifact storage to S3

`S3_BUCKET=pacopilot-s3`, `S3_REGION=eu-north-1`. Where the credentials
go depends on which machine you mean, and getting this wrong is silent:

**On Render (and any real host).** Set `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` as dashboard environment variables. Those become
the process environment, which is the first place boto3 looks, so
nothing else is needed. Better still on EC2/ECS: attach an instance role
and set neither — no long-lived key exists to leak.

**Locally, in `backend/.env`.** This is the case that does not work by
itself. pydantic-settings reads `.env` into the settings object and
never exports it to `os.environ`, so boto3's credential chain cannot see
it. Both keys are therefore declared in `Settings` and passed to the
client explicitly when present. Two consequences:

- A key in `.env` that is *not* declared in `Settings` does not merely
  go unused — `Settings` forbids unknown keys, so the app fails to
  start, and the pydantic error quotes the offending value. That is a
  credential in a stack trace. Declare before adding.
- Paste the raw values. `AKIA...`, not `<AKIA...>` — the angle brackets
  from a placeholder become part of the string and AWS answers
  `InvalidAccessKeyId`.

Verify with the live round-trip, which skips when unconfigured so a
green run on a bare machine is never mistaken for proof:

```bash
cd backend && python -m pytest tests/unit/reports/test_s3_storage.py -q
```

26 passed means the bucket really accepted an upload, returned it byte
for byte, refused a cross-tenant read, and cleaned up. 25 passed with
one skip means it never contacted AWS at all.

The IAM user needs only `s3:PutObject`, `s3:GetObject` and
`s3:DeleteObject` on `arn:aws:s3:::pacopilot-s3/*`. Notably **not**
`s3:ListBucket` — nothing in the application enumerates the bucket, and
withholding it means a leaked key cannot even discover what is stored.
One consequence when debugging by hand: without `ListBucket`, S3 answers
`403` instead of `404` for an object that is not there, deliberately, so
that a caller cannot probe for existence. A 403 on HEAD is what a
successfully deleted object looks like.

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
