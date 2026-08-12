# Security remediation note — credential exposure

**Date raised:** 2026-08-12
**Raised by:** report-automation POC work (Section 0 security stop)
**Status:** ACTION REQUIRED BY THE USER — no automatic remediation performed

No credential values appear anywhere in this document, and none were
copied into source, logs, worker configuration, or the implementation
report.

---

## 1. What was scanned

| Scope | Method | Result |
|---|---|---|
| Tracked repository files | `git grep` for provider key formats | **Clean** — one match, a hard-coded *fixture* string in `backend/tests/unit/services/test_google_oauth.py` (`test-client-id.apps.googleusercontent.com`), which is not a credential |
| Full git history, all refs | `git log --all -S` for provider key formats | **Clean** — no commit ever introduced or removed a matching value |
| `.gitignore` coverage | direct read | **Correct** — `.env`, `backend/.env`, `.env.local`, `frontend/.env.local` all ignored |
| Local env files | presence check + key-name listing | `backend/.env` present and correctly ignored |

**The repository itself is not leaking secrets, and history does not need
rewriting.** No `git filter-repo` / BFG action is required.

## 2. Where live credentials are exposed

### 2.1 `C:\Users\kotes\.claude\CLAUDE.md` (global Claude Code instructions)

This file is **outside the repository** and is **read into context at the
start of every Claude Code session, in every project**. It currently
contains plaintext values in these categories:

| Category | Provider | Sensitivity |
|---|---|---|
| LLM API key | Anthropic | Billable; full account API access |
| LLM API key | OpenAI | Billable; full account API access |
| LLM API key | Moonshot / Kimi | Billable |
| LLM API key | Google Gemini | Billable |
| ML platform token | Hugging Face | Repo read/write depending on scope |
| OAuth client secret | Google (`pa-copilot` client) | Enables auth-flow impersonation of the app |
| OAuth client ID | Google (`pa-copilot` client) | Not secret by design — no action needed |
| Enterprise system API key | IBM Planning Analytics | **Highest impact** — direct access to a customer-facing TM1/PA environment |

### 2.2 `backend/.env`

Correctly located and correctly ignored by git. Holds `SECRET_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID` and the
local database credentials. **This is the right place for them** — no
change needed beyond ensuring the values are the *rotated* ones once
rotation happens.

Note: `TM1_CREDENTIALS_KEY` is absent from `backend/.env`. TM1 connection
create/read will fail until it is set (`Fernet.generate_key()`). It is
not required for the report-automation POC, which does not decrypt TM1
credentials.

## 3. Required actions (user-performed)

Rotation was **not** performed automatically — it requires provider
consoles this environment has no authorized access to.

1. **Rotate every credential in the categories listed in 2.1.** Prioritise
   the IBM Planning Analytics key and the Google OAuth client secret; the
   LLM keys are billable but lower blast radius.
2. **Remove the plaintext block from `C:\Users\kotes\.claude\CLAUDE.md`.**
   Replace it with a pointer, e.g. *"API keys are in `backend/.env` and
   the Render dashboard — never paste values into instructions."*
3. **Re-set rotated values** in `backend/.env` (local) and the Render
   dashboard (`sync: false` vars in `render.yaml`).
4. **Review provider audit logs** for use of the exposed keys since they
   were first written into that file.

## 4. How this feature avoids adding to the problem

The report automation implementation introduces new secrets (worker
enrollment tokens and worker credentials). Design decisions taken to keep
them out of this failure mode:

- Worker secrets are stored only as **HMAC-SHA256 digests keyed with
  `SECRET_KEY`** — never plaintext, never reversible from a database dump
  alone (`src/reports/worker_credentials.py`).
- The raw enrollment token and worker credential are returned **exactly
  once**, at the moment of creation, and never appear in any subsequent
  API response, list view, or log line.
- Worker request logs redact `Authorization` headers and never emit the
  credential (`worker/pa_worker/logging.py`).
- TM1 credentials are **never included in a job payload sent to a
  worker**. Where a report references a TM1 connection, the worker
  receives the connection's non-secret coordinates only.
- Worker access tokens are short-lived (default 15 minutes) and carry a
  `sv` (secret version) claim, so rotating a credential invalidates every
  token already in flight without a revocation table.
