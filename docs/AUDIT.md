# PA-Copilot Recon Audit (2026-07-26)

Recon pass ahead of the SaaS-upgrade tenancy phase. Facts only — verified against the code, not aspirational.

## Frontend

- Next.js + Tailwind v4 + shadcn/ui (on Base UI, not Radix).
- `frontend/src/app/globals.css`: has `@theme inline { ... }` (Tailwind v4's mechanism mapping CSS vars to utilities, e.g. `--color-primary: var(--primary)`), a `:root { ... }` block and a `.dark { ... }` block with color tokens. **No** `@supports (color: lab(0% 0 0))` block exists. Brand tokens (`--primary`, `--secondary`, `--accent`, `--border`, `--chart-*`, `--sidebar-*`) are hex; base neutrals (`--background`, `--foreground`, `--card`, `--popover`, `--destructive`) are `oklch(...)` — a mixed color-space split already present in both light and dark blocks. Current `--primary` is `#1877f2` (light) / `#4e9bff` (dark) — Facebook blue, not indigo.
- `next-themes` (`^0.4.6`) is already installed and fully wired: `frontend/src/components/providers.tsx` wraps the app in `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>`. `frontend/src/app/layout.tsx`'s `<html>` has `suppressHydrationWarning` and no hardcoded theme class.
- A theme toggle (`frontend/src/components/theme-toggle.tsx`, `useTheme()`) already exists in the authenticated app header (`app-header.tsx`) and a fuller light/dark/system selector on the Settings page. **Not present on the public landing page.**
- No reusable `<Footer>` component exists. The landing page's inline footer (`frontend/src/app/page.tsx`) has only "Sign in" / "Sign up" links — no legal/trust links.
- Metadata: only `title`/`description` set in `layout.tsx`. No `openGraph`, `twitter`, `robots`, or `generateMetadata` anywhere in the app.
- Landing page copy (`page.tsx`) and the request-access flow (`request-access/page.tsx`) were read in full: no contradiction found between the security section and the closing CTA — both describe consistent self-serve signup with admin-revocation.
- No `/security`, `/privacy`, `/terms`, `/subprocessors`, `/docs`, `/status`, `/contact` routes exist anywhere.
- No Stripe/billing code anywhere in the frontend.

## Backend

- FastAPI, async SQLAlchemy 2.0.51, asyncpg, Alembic migrations, PostgreSQL.
- `backend/src/database/session.py`: `AsyncSessionLocal` is a plain `async_sessionmaker`; `get_db()` is a simple per-request context manager (commit on success, rollback on exception) — not a Unit-of-Work object.
- `backend/tests/conftest.py` overrides `get_db` wholesale for tests (`app.dependency_overrides[get_db] = override_get_db`), yielding a hand-built session bound to a transaction+savepoint — any logic inside the real `get_db()` body would silently not run under test.

## Data model

`BaseModel` gives every table `id`/`created_at`/`updated_at` only — no tenant column by default; each model opts in individually.

Tenant-scoped tables with `organization_id` NOT NULL + indexed: `TM1Connection`, `KnowledgeDocument`, `KnowledgeChunk`, `AIConversation`, `AIUsage`, `AIToolExecution`, `TM1Object`, `TM1Relationship`, `TM1Change`, `User`.

Nullable `organization_id` **by deliberate design**: `Role` (NULL = global/system role shared across every org) and `AuditLog` (NULL = owning org was hard-deleted, `ondelete="SET NULL"`).

No own `organization_id`: `AIMessage` (reachable only transitively via `conversation_id → AIConversation.organization_id`; no `get_by_id` method exists on its repository, and every read path already goes through the parent conversation's ownership check first).

No file/attachment/blob table exists — `KnowledgeDocument` stores only metadata; raw bytes are read in-memory during upload, chunked, and embedded, never persisted.

## Auth

- JWT-based sessions (`get_current_user`/`get_current_active_user` in `backend/src/api/dependencies/auth.py`), Google OAuth wired in `login/page.tsx` (ID-token verification only, no client secret/authorization-code exchange).
- `require_permission(code)` (`backend/src/api/dependencies/permissions.py`) does a **live, uncached** DB permission check every request (`Permission → RolePermission → UserRole` join) — revocation takes effect immediately, no stale JWT-claim trust.
- Every mutating (POST/PUT/PATCH/DELETE) endpoint across `backend/src/api/v1/*.py` has a permission/auth dependency, except the intentionally-public auth flows and health checks.
- Org-ownership enforcement today is a consistent **service-layer convention**, not a repository- or session-level guarantee: every by-ID service method checks `if resource is None or resource.organization_id != current_user.organization_id: raise NotFoundException` (correctly 404, not 403). Applied via one centralized choke point for TM1 resources (`TM1IntegrationService.get_connection`, reused at 27 call sites) and per-service for knowledge documents, users, roles, and TM1 metadata. AI conversations use a stricter ownership check (`conversation.user_id != user_id`, private per-user not just per-org).
- Repository `get_by_id(db, id)` methods filter by primary key alone with zero org-awareness — the gap Phase 1 exists to close as a backstop.

## AI layer

- No dedicated intent classifier. Persona selection is explicit — the caller passes an `agent` name; there is no NL-based agent inference.
- Within a persona, tool routing is 100% native Claude tool-calling (`_run_tool_loop` in `backend/src/ai/orchestrator.py`), with a server-side `allowed_tools` allowlist as a hard backstop if the model tries a disallowed tool. `MAX_TOOL_ROUNDS` defaults to 5, per-persona override capped at 15.
- 21 tools registered in `backend/src/ai/tools/registry.py`, spanning cube/dimension/process/chore metadata reads, MDX execution (capped at 500 cells), dependency-graph analysis (BFS-based, capped at 1000 nodes), knowledge-base RAG search, and two human-gated draft tools (`propose_rule_update`, `propose_process_update`).
- 9 personas, loaded dynamically from YAML in `backend/src/ai/prompts/` (duplicate names fail fast at startup) — no Python change needed to add a persona.
- Security-group/log/performance-cube reads are a **live, intentional gap**: `security_service.py` already wraps `client.security.get_all_groups`/`get_user_names_from_group` at the TM1py-client level, but no tool exposes it, and every persona's `safety_notes` explicitly disclaims security-group access. `}Clients`/`}Groups`/`}ClientGroups` control-cube reads, `tm1server.log` reads, and `}Stats*`/`}PerfCubes` reads are entirely greenfield — no scaffolding exists for any of them. TM1py itself exposes most of what would be needed as thin Python methods (`client.server.*`, `client.monitoring.*`), so new tools follow the existing `call_with_resilience(connection_id, client.<namespace>.<method>)` pattern rather than needing new REST plumbing.

## Approval workflow

- `TM1Change` / `tm1_changes` table. `change_type` is an unconstrained `String(30)` — no DB enum/check constraint, validated only in application code (`VALID_CHANGE_TYPES` in `backend/src/tm1/deployment/change_service.py`): `update_rules`, `create_process`, `update_process`, `delete_process`.
- Lifecycle: `draft → executed | failed → rolled_back`, or `draft → rejected`.
- Snapshot/verify/restore logic lives entirely in `ChangeService`: `create_change` (validates + pre-checks + compile-dryrun for processes + impact analysis, persists as draft), `execute_change` (snapshots `previous_content` immediately before applying, applies, verifies, auto-restores + marks `failed` on verify failure), `rollback_change` (restores from snapshot, executed-only), `reject_change` (discards a draft, never touches the live server).
- Extensibility is manual: adding a new change type means touching `if/elif` branches across 4 methods plus a new `propose_*` AI tool — no plugin/dispatch-table abstraction. No migration needed for new type strings since the column isn't a DB enum.

## Existing tests

- `backend/pytest.ini`: `asyncio_mode = auto`, `testpaths = tests`, a `live` marker for tests requiring a real TM1 server.
- Real Postgres, transaction+savepoint isolation per test (`backend/tests/conftest.py`).
- 339 test functions across `unit` (40 files), `integration` (16 files), `live` (8 files, need a real TM1 server), `performance` (0 files, empty dir) — 91 total test files.
- Existing cross-org regression tests (two-orgs-assert-404 pattern): TM1 connections, knowledge documents, user approve/deactivate. **Missing**: `tm1_changes` (draft/execute/rollback), knowledge search/ask (RAG retrieval), audit log listing, roles listing, AI conversations (only cross-*user* same-org is tested, not cross-org).

## Phase 1 addendum — implementation notes

`src/database/tenancy.py` implements the session-level org-scoping backstop described above (`OrganizationScoped` mixin + `do_orm_execute` listener, gated by `TENANCY_ENFORCEMENT_ENABLED`, default `False`). Two things discovered only once real tests ran against it, worth recording:

1. **`with_loader_criteria`'s callable form is cache-unsafe here.** The first implementation passed a `lambda cls: ...` per model to `with_loader_criteria`, which ties into SQLAlchemy's per-class cache-key machinery (meant for polymorphic "adapt per queried subclass" scenarios) and does not reliably re-evaluate the closed-over `org_id` on every execution. Fixed by building the plain boolean expression directly (`model.organization_id == org_id`) inside the loop instead of wrapping it in a callable — this matches SQLAlchemy's own documented multi-tenancy pattern and is evaluated fresh on every `do_orm_execute` regardless of downstream statement caching.
2. **`User` being `OrganizationScoped` creates a chicken-and-egg risk during authentication.** `get_current_user` must fetch the caller's own `User` row by ID *before* it knows which org to stamp on the session. If a session previously had a different org stamped (impossible in production, where every request gets a fresh `AsyncSession`, but true of this test suite's `client` fixture, which reuses one session across an entire test's multiple simulated requests), that stale org id would filter out the *new* user's own self-lookup and silently break authentication. Fixed by clearing `db.info["organization_id"]` immediately before the self-lookup in `get_current_user` (`api/dependencies/auth.py`), then stamping the freshly-resolved value after. Caught by the new cross-org regression tests, not by inspection — a good example of why the "flip the flag on in staging and run the full suite" rollout step (rather than trusting the design alone) was the right sequencing.
