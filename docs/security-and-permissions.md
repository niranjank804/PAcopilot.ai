# Security & Permissions Reference

The authoritative source is always `backend/scripts/seed_permissions.py` and
`backend/scripts/seed_roles.py` — this doc explains and organizes what's
defined there, current as of 2026-07-23. If the two disagree, the scripts
are right and this doc is stale.

## 1. The five system roles

| Role | Intent |
|---|---|
| **Super Admin** | Full access across all organizations. |
| **Organization Admin** | Full access within one organization. |
| **Planner** | Plans and analyzes; same permission set as Analyst today (no dedicated Planner-only resource exists yet). |
| **Analyst** | Views and analyzes; same permission set as Planner today. |
| **Viewer** | Read-only, and notably **cannot** touch live TM1 systems at all (see §3). |

Roles are **system-defined** (`is_system=True`, `organization_id=None`) —
every organization gets the same five roles automatically; there's no
per-org custom role UI today (the API supports creating custom org-scoped
roles via `roles.write`, but nothing in the frontend exposes it yet).

## 2. Every permission that exists today

| Permission | What it actually gates |
|---|---|
| `users.read` | View the member list and pending access requests (`GET /users`). |
| `users.write` | Approve/reject access requests, deactivate/reactivate members, assign/remove roles. **Does not include deleting a user** — that's the separate `users.delete`, and no endpoint uses it yet. |
| `users.delete` | Reserved — not wired to any endpoint yet. |
| `roles.read` | View roles and their permission lists. |
| `roles.write` | Create/update/delete roles (system roles are protected — `PermissionDeniedException` if you try). |
| `organization.read` / `organization.write` | View/update org details — no endpoint uses `.write` yet. |
| `audit.view` | Read the audit log (every write action in this app is logged here — see §6). |
| `ai.chat` | Use `/ai/chat` and `/ai/chat/stream` at all (with or without a persona). |
| `knowledge.read` | Search the knowledge base, ask grounded questions, **and** `/knowledge/explain-error`. |
| `knowledge.write` | Upload/delete knowledge base documents. |
| `tm1.read` | View TM1 connections, query cube/dimension/process/chore metadata, run the dependency graph, run `/tm1/.../visualize`. |
| `tm1.write` | Create/delete TM1 connections, **and** draft a change (`propose_rule_update`/`propose_process_update`, or `POST /changes` directly). |
| `tm1.security.read` | View TM1's own internal security groups/membership — deliberately narrower than `tm1.read` and never exposed as an AI tool (enforced by a regression test — see §5). |
| `tm1.deploy` | Execute or roll back a drafted change on the live TM1 server. |
| `monitoring.view` | View AI usage / tool / TM1 circuit-breaker status dashboards. |

## 3. Who has what, exactly

```
READ_ONLY            = users.read, roles.read, organization.read, audit.view
GENERAL               = READ_ONLY + ai.chat, knowledge.read, monitoring.view
PLANNING (Planner/Analyst) = GENERAL + tm1.read
```

| | Viewer | Planner / Analyst | Org Admin / Super Admin |
|---|---|---|---|
| Read users/roles/org/audit | ✅ | ✅ | ✅ |
| AI chat, knowledge base | ✅ | ✅ | ✅ |
| Monitoring dashboards | ✅ | ✅ | ✅ |
| **View TM1 data at all** | ❌ | ✅ | ✅ |
| Draft a TM1 change (`tm1.write`) | ❌ | ❌ | ✅ |
| **Execute/roll back a TM1 change** (`tm1.deploy`) | ❌ | ❌ | ✅ |
| View TM1 security groups (`tm1.security.read`) | ❌ | ❌ | ✅ |
| Approve/reject access requests, deactivate users | ❌ | ❌ | ✅ |
| Manage roles | ❌ | ❌ | ✅ |

**The two sharpest lines in the whole model:**
- **Viewer has zero TM1 access.** `tm1.read` was deliberately left out of
  `GENERAL_ROLE_PERMISSIONS` — TM1 connections hold live credentials to a
  real enterprise system, so "can view dashboards" does not imply "can see
  TM1 data."
- **Drafting and executing are two different permissions.** Only
  `tm1.write` is needed to draft a rule/process change (the AI can do this
  autonomously via `propose_rule_update`/`propose_process_update`); only a
  human holding `tm1.deploy` can actually apply it to the live server. The
  AI's tool registry is guarded by a regression test
  (`test_no_ai_tool_can_execute_or_roll_back_a_change`) that fails the
  build if any future tool tries to call the execute/rollback code path
  directly — see `docs/ai-features-development-guide.md`.

## 4. Getting an account — the approval gate

Added 2026-07-23. Two independent gates sit in front of every login,
checked in this order (`auth_service._check_can_authenticate`):

1. **`registration_status`**: `pending` → `approved` → (or `rejected`).
   Set once, by an Org Admin, never automatic. New accounts start
   `pending` regardless of how they're created (self-service or Google
   sign-in only ever *logs into* an existing account, never creates one).
2. **`is_active`**: independent of the above — an Org Admin can
   deactivate/reactivate an *already-approved* account at any time (e.g. an
   employee leaving) without touching their registration history. An admin
   cannot deactivate their own account (blocks accidental lockout).

| Path | What happens |
|---|---|
| `POST /auth/register` | Creates a `pending` user under the given `organization_code` (a human-typeable invite code, not a raw UUID). Cannot log in yet. |
| `GET /users?registration_status=pending` | Org Admin's queue of requests to decide on. |
| `POST /users/{id}/approve` | `pending → approved`; optionally assigns a role in the same call. |
| `POST /users/{id}/reject` | `pending → rejected` — permanent, no un-reject endpoint (re-register if that's ever needed). |
| `POST /users/{id}/deactivate` / `.../activate` | Toggles `is_active` on an approved account. Self-deactivation is blocked (422). |

All four admin actions are `users.write`-gated, scoped to the caller's own
organization (cross-org access attempts get a 404, not a 403 — doesn't
even confirm the target exists), and audit-logged.

## 5. Read boundaries the AI specifically respects

- **Security groups are never an AI tool.** `tm1.security.read` exists
  only as a direct API permission; no tool in the AI tool registry can
  reach it, enforced by `test_security_groups_are_never_exposed_as_ai_tools`.
- **Every AI tool re-checks its own permission** inside `execute()` via
  `auth_repository.user_has_permission` — tools run inside the
  orchestrator's loop, not through FastAPI's `Depends`, so there's no
  routing-layer gate to lean on; each tool enforces its own.
- **Personas further narrow the tool set** on top of the user's actual
  permissions — e.g. the `analyst` persona only exposes read/MDX tools even
  though the acting user might also hold `tm1.write`.

## 6. Everything is audited

Every write path in this app — TM1 connection changes, drafts,
execute/rollback, role assignment, user approval/rejection/(de)activation
— writes an `AuditLog` row (`organization_id`, `user_id`, `action`,
`entity`, `entity_id`, before/after values, IP, user agent). Read via
`GET /audit` (`audit.view`, general permission — every role has it).

## 7. Authentication mechanisms

Three ways to get a session, all producing the same JWT pair:

| Method | Notes |
|---|---|
| Username/password | `argon2` hashing (`PASSWORD_HASH_SCHEME`). |
| Google Sign-In | Verifies a real Google-issued ID token (`google-auth`, checks signature/audience/expiry/`email_verified`) — **never creates an account**, only logs into one whose email already exists and is approved+active. No client secret involved; see `docs/ai-features-development-guide.md`-adjacent notes in `src/services/google_oauth.py`. |
| Password reset | Single-use, 30-minute-expiry token (SHA-256 hash stored, not the raw token), delivered via a swappable `EmailProvider` (SMTP if configured, otherwise logged to `logs/application.log` for local dev — see `src/email/`). `request_password_reset` is a **silent no-op for an unknown email**, specifically to prevent account enumeration. |

Sessions: JWT **access** token (`ACCESS_TOKEN_EXPIRE_MINUTES=30`) +
**refresh** token (`REFRESH_TOKEN_EXPIRE_DAYS=7`), rotated on every
`/auth/refresh` call (old refresh token is not reusable after rotation).
Tokens are stored in `localStorage` on the frontend, not httpOnly cookies
— a known, documented trade-off (see `[[project_backend_architecture]]`
memory, Frontend Round 1) worth revisiting if this app's XSS exposure ever
grows enough to justify the extra complexity.

## 8. Data isolation

- **Every** query in every service is scoped by `organization_id` — there
  is no cross-org read path anywhere in the codebase; attempts return 404,
  not 403 (existence isn't even confirmed to a caller outside the org).
- **TM1 connection credentials** are encrypted at rest with
  `cryptography.fernet` (`TM1_CREDENTIALS_KEY`), decrypted only at the
  point of building a live TM1py client — never logged, never returned by
  any API response.
- **Password reset tokens** and **user password hashes** are never stored
  or transmitted in raw form — only hashes.
