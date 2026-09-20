# Changelog

## 2026-09-21

Remediation of the P0 and P1 findings of the engineering audit
(`docs/security-and-permissions.md` §9 lists the new defaults).

### Fixed
- **Open registration.** Self-registration and first-time Google sign-in created approved accounts in the shared default organization with `tm1.read`; anyone who found the sign-up page could read the connected TM1 model. New accounts start `pending` and cannot obtain a token until an Org Admin approves them. `REGISTRATION_AUTO_APPROVE=true` restores the testing-phase behaviour for a deployment strangers cannot reach.
- **Tests ran against production.** The backend suite built its engine from `backend/.env`, which pointed at the Neon production database. It now refuses any non-local host and uses the docker-compose `enterprise_ai_test` database (`make test-db`).
- **CI had been red since 2026-09-06** (numpy 2.5.1 needs Python ≥ 3.12; the matrix ran 3.11). Matrix is now 3.12 and 3.14. `pypdf`, `cryptography` and `next` upgraded past their advisories; both dependency audits pass.
- **Quota bypasses.** A chat request could name any model (now `AI_ALLOWED_MODELS`); a stream closed before `done` was never charged (interrupted turns are now recorded, with the partial answer kept); concurrent requests at the edge of the limit all passed (turns in flight are now counted).
- **TM1 calls could hold threads forever** (no TM1py timeout; shared executor). Every client now has a request timeout, calls run on a bounded pool, dropped clients are logged out.
- **TM1 error messages leaked the upstream response** (body and headers, to a caller who chose the address). Callers get the status and reason; the log gets the rest. Loopback, link-local and private IP addresses are refused unless `TM1_ALLOW_PRIVATE_ADDRESSES` is on.
- **Security-headers and request-id middlewares were never registered.** They are now; every log line carries the request id.
- **Password-reset links were printed to the log** when SMTP was unset. Production without SMTP drops the message and warns at startup.
- PDF parsing, chunking, zip expansion and TI parsing no longer run on the event loop; those routes share a new `heavy` rate-limit window.

### Changed
- `LOG_FILE` (unset by default) replaces the unconditional `logs/application.log` sink, which would fail on Vercel's read-only filesystem.
- Orphaned pins removed from `requirements.txt` (xgboost, joblib, threadpoolctl, pyarrow, narwhals, reportlab).

## 2026-07-25

### Added
- **House-Style Code Generation** — the TI and Developer agents now call `search_knowledge_base` before drafting any TurboIntegrator process, rule, or feeder, learn the organization's naming/logging/error-handling/comment conventions from whatever reference material exists, and write new code in that same style rather than generic TM1 templates. When no exact reference exists, the style is inferred from whatever standards the Knowledge Base does hold, falling back to generic TM1 practice only when none exist at all — and saying so plainly.
- TI process drafts (`propose_process_update`) can now declare a `datasource_type`, its variables, and its parameters, so a process meant to read a file (e.g. an ASCII/CSV import) actually compiles instead of referencing undefined source columns.
