# Rotating secrets

## Why this exists

The entire production secret set was found configured on the
`pa-copilot-frontend` Vercel project: `TM1_CREDENTIALS_KEY`,
`SECRET_KEY`, `DATABASE_PASSWORD`, `AWS_SECRET_ACCESS_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and the rest.

**Nothing leaked to browsers.** Next.js inlines only `NEXT_PUBLIC_*`
into the client bundle, and none of these carry that prefix — verified
by scanning all 15 chunks of the live bundle for secret-shaped strings,
which found none.

The real exposure is narrower but genuine: Vercel makes environment
variables available **during the build**, and npm install scripts run
in that build. The deployment log lists three packages with install
scripts (`esbuild`, `sharp`, `unrs-resolver`). Any package in that
dependency tree has been able to read every one of those secrets on
every build. Those three are reputable and there is no evidence of
compromise — but Dependabot has been opening PRs bumping dozens of
packages, and "unused by the frontend" is not the same as "unreachable".

The frontend reads exactly five variables:

    NEXT_PUBLIC_API_URL  NEXT_PUBLIC_GOOGLE_CLIENT_ID
    NODE_ENV  VERCEL  VERCEL_ENV

Everything else on that project should be deleted.

## Cost of rotating each secret

| Secret | Effect of rotating | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | new key, redeploy |
| `OPENAI_API_KEY` | none | knowledge search breaks until redeployed |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | none | IAM → new key → delete old |
| `DATABASE_PASSWORD` | brief interruption | rotate in the provider, redeploy |
| `SECRET_KEY` | **everyone is logged out** | JWTs signed with the old key stop verifying. Harmless, but do it deliberately |
| `TM1_CREDENTIALS_KEY` | **see below** | naive rotation destroys every stored TM1 password |

## Rotating `TM1_CREDENTIALS_KEY` without losing credentials

This key encrypts two columns: `tm1_connections.encrypted_password` and
`planning_analytics_connections.encrypted_credential`.

Changing it naively makes every stored credential permanently
undecryptable, and the only recovery is asking each user to re-enter
their TM1 password. That is what made the key effectively unrotatable —
impossible to change at exactly the moment a suspected exposure means
it should be.

`src/tm1/crypto.py` now uses `MultiFernet`, which encrypts with the
first key and decrypts with any. Rotation is three steps, and no step
can lose data.

### Step 1 — run both keys

```bash
TM1_CREDENTIALS_KEY=<new key>          # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TM1_CREDENTIALS_KEY_PREVIOUS=<old key>
```

Deploy. Nothing breaks: existing rows decrypt under the previous key,
new writes use the new one.

### Step 2 — re-encrypt what is stored

```bash
cd backend
python scripts/rotate_tm1_key.py --dry-run   # count first
python scripts/rotate_tm1_key.py
```

One row per transaction, so an interrupted run is safe — some rows end
up on the new key and some on the old, and both still decrypt while
step 1's configuration is in place. Re-running is a no-op for rows
already moved.

Plaintext is never materialised: `MultiFernet.rotate` decrypts and
re-encrypts internally, so no password is ever held in a variable that
could be logged.

A row encrypted under a key that is configured nowhere is reported by
id and skipped rather than aborting the run. Those connections need
their credentials re-entered — nothing else can recover them.

### Step 3 — retire the old key

Remove `TM1_CREDENTIALS_KEY_PREVIOUS` and redeploy. The old key is now
dead.

### Verification

`tests/unit/tm1/test_crypto_rotation.py` covers each step, including
that a half-rotated table is fully readable. The script itself was run
end to end against a real database row: seeded under the old key,
rotated, then confirmed to decrypt under the new key alone and to be
unreadable by the old one.

## Order of work

1. Delete every variable except the two `NEXT_PUBLIC_*` ones from the
   `pa-copilot-frontend` Vercel project.
2. Rotate the cheap ones: Anthropic, OpenAI, AWS, database password.
3. Rotate `SECRET_KEY` when a forced logout is acceptable.
4. Rotate `TM1_CREDENTIALS_KEY` by the three steps above — or leave it,
   given there is no evidence of exposure, now that doing so is no
   longer a one-way door.
