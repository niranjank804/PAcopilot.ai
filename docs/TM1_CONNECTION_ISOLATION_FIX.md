# TM1 connection isolation fix

Date: 2026-10-03. Branch `fix/audit-findings-2026-09-13`.

## 1. Problem

The owner created TM1 connections (including an on-premises server reached
through a gateway). Another person who signed in with a different email saw
those connections in their connection list — and could select and use them.

## 2. Actual root cause

Two things together.

**a. Connections had no owner-level boundary.** Every lookup of a TM1
connection goes through `tm1_integration_service.get_connection`
(`backend/src/tm1/service.py`) and every listing through
`list_connections`. Both filtered by **organization only**:

```python
# before
if connection is None or connection.organization_id != organization_id:
    raise NotFoundException("TM1 connection not found.")
...
return await tm1_connection_repository.list_by_organization(db, organization_id)
```

`TM1Connection.created_by` was recorded but never consulted. So every member
of an organization holding `tm1.read` saw every connection in it, and
`tm1.read` plus the route's own permission let them use it.

**b. Every sign-up used to join the same organization.** Before commit
`935803f` (2026-09-30), self-registration and first Google sign-in without
an organization code placed the account in the shared `default`
organization — the owner's. So "a different account" was a member of the
owner's organization, and (a) applied.

`935803f` stopped (b) for new sign-ups (each now gets a private workspace).
Accounts created before it, and colleagues who join with an organization
code, are still in a shared organization — which is why (a) needed fixing.

## 3. Existing ownership model (as found)

Organization-shared: `tm1_connections.organization_id` (owner organization)
and `created_by` (creator, NOT NULL, set from the session). No visibility or
sharing field.

## 4. Existing organization model

`organizations`; every user has one `organization_id`. A session-level filter
(`src/database/tenancy.py`) restricts organization-scoped models to the
caller's organization; services also check it explicitly.

## 5. Existing RBAC model

System roles Super Admin, Organization Admin (both hold every permission
code), Planner, Analyst (`tm1.read`), Viewer, plus custom roles.
TM1 permissions: `tm1.read`, `tm1.write`, `tm1.deploy`, `tm1.deploy.qa`,
`tm1.deploy.prod`, `tm1.execute`, `tm1.security.read`.

## 6. Exact backend path that caused the leak

`GET /tm1/connections` → `api/v1/tm1.py:list_connections` →
`tm1_integration_service.list_connections(db, org_id)` →
`tm1_connection_repository.list_by_organization` → every row of the
organization. Every other path (`GET/PATCH/DELETE /connections/{id}`,
`/test`, cubes, processes, changes, visualize, metadata, health, the AI
tools, report automation, monitoring status) resolved the connection by
organization only in the same way.

## 7. Exact fix

The model becomes **hybrid**, reusing `created_by` as the owner:

- New field `tm1_connections.visibility`: `private` (default) or
  `organization`.
- **Private** — only its creator sees and uses it.
- **Organization** — every member with the right permission, as before.
- **Organization admins** (new permission `tm1.connections.manage_all`,
  held by Organization Admin and Super Admin) may *see and manage*
  (list, rename, share, delete) a member's private connection, but **not
  use** it (no test, no queries, no changes): administration, not
  impersonation with someone else's TM1 credentials.

One decision point, `TM1IntegrationService.may_access(connection, purpose,
user_id)`, used by `get_connection(..., purpose="use"|"manage")` and
`list_connections(..., purpose=...)`. The user comes from
`db.info["user_id"]`, stamped by the authentication dependency
(`api/dependencies/auth.py`) next to the organization the tenancy filter
already used — or passed explicitly. A session with no user (scheduled
jobs, scripts) is the system and unrestricted.

A refused connection raises the same `NotFoundException("TM1 connection not
found.")` as a missing one (the existing non-disclosure convention): no
existence, name or server is revealed.

Changing a connection's visibility is limited to its owner or an
organization admin, so a member using a shared connection cannot make it
private to themselves.

## 8. Database changes

Migration `f9b3d5e7a1c2_connection_visibility`: adds
`tm1_connections.visibility VARCHAR(20) NOT NULL DEFAULT 'private'` with a
check constraint. New permission `tm1.connections.manage_all` is created by
`scripts/seed_permissions.py` (run by every deploy).

## 9. API changes

- `ConnectionCreate` / `ConnectionUpdate` accept `visibility`.
- `ConnectionResponse` adds `visibility`, `created_by`, and `can_use`
  (false for an admin viewing a member's private connection).
- `GET /tm1/connections` and `GET /tm1/connections/{id}` use `manage`;
  `PATCH` and `DELETE` use `manage`; every other connection route uses
  `use`. Unauthorized → 404, as for a missing connection.
- `GET /monitoring/tm1-status` lists only connections the caller may see.
- Report automation only accepts a connection the user may use.

## 10. Frontend changes

- Connection form: "Who can use it" — *Only me* (default) or *Everyone in
  my organization*.
- Connection cards: *Private* / *Shared* / *Member's private* badge; no
  Test or View details on a connection the viewer may not use.
- Every connection picker (chat, dashboard, deployments, metadata, model
  health, visualize) loads `fetchUsableConnections()`
  (`frontend/src/lib/connections.ts`), which drops `can_use: false` rows.
  This is presentation only; the server is the boundary.

## 11. AI / tool security changes

- The orchestrator's tool dispatcher (`ai/orchestrator.py:_execute_tool_call`)
  resolves any model-supplied `connection_id` through `get_connection` with
  the conversation's user **before** the tool runs. Several tools read the
  dependency map by id without loading the connection; this single check
  covers all of them. A refused id returns "TM1 connection not found." to
  the model and is recorded in the tool audit.
- The connection list in the AI system prompt uses `list_connections` with
  the user, so the model is only told about connections the user may use.
- Credentials are never in tool arguments, prompts or responses
  (unchanged; `ConnectionResponse` has no password field).

## 12. Test coverage

`backend/tests/integration/tm1/test_connection_isolation.py` (10 tests):

| # | Scenario | Result |
|---|---|---|
| 1 | A sees own connection | pass |
| 2 | B does not see A's | pass |
| 3 | B creates own; sees it, not A's; A does not see B's | pass |
| 4 | B `GET /connections/{A}` → 404, same body as a missing id | pass |
| 5 | B `PATCH` A's → 404 | pass |
| 6 | B `DELETE` A's → 404, row still there | pass |
| 7 | B `POST …/test` on A's → 404, no TM1 client created | pass |
| 8 | B lists cubes / drafts a change on A's → 404, no TM1 client | pass |
| 9 | AI tool with A's id in B's conversation → refused, no TM1 client; also a dependency-map tool | pass |
| 10 | Another organization: no access even to a shared connection | pass |
| 11 | Shared connection usable by members; a member cannot make it private | pass |
| 12 | Admin sees member's private (`can_use: false`), renames and deletes it, cannot test or use it | pass |
| — | No response carries the TM1 password | pass |
| — | Ownership comes from the session, not the body | pass |
| — | Monitoring status hides another member's private connection | pass |

Updated: governance and promotion tests create their QA/PROD connections as
shared (team servers that a second approver must use).

Full suites: backend 1608 passed, 19 skipped; frontend 237 passed.

## 13. Browser verification

Local copy (frontend :3123, backend :8002) against a scratch database
`pa_iso_check` — not production — with two ordinary members of one
organization, driven by Playwright through the real UI. 11/11 checks:

- A creates "User A Dev" and sees it.
- B does not see "User A Dev"; creates "User B Dev" and sees it; still not
  "User A Dev".
- With B's own session, direct API calls on A's connection — read, test,
  list cubes, delete — all 404; B's list returns only "User B Dev".
- A signs in again: sees "User A Dev", not "User B Dev".

Screenshots: `docs/evidence/connection-isolation/`.

**Not verified:** the same flow on the production site (needs the deploy and
two real accounts).

## 14. Migration details — existing data

Every existing connection becomes `private`, owned by its `created_by`
(NOT NULL, so every row has an owner). Effect on deploy:

- Each person keeps every connection they created.
- Members stop seeing connections other people created. If a colleague
  should keep using one, its owner (or an organization admin) sets
  "Who can use it" to *Everyone in my organization*.
- Organization admins still see every connection in their organization
  (marked *Member's private* when it is not theirs).

Nothing is reassigned or deleted. To review existing records before or after
deploying, run in the Neon SQL editor (read-only):

```sql
SELECT c.name, c.address, c.visibility, o.name AS organization,
       u.email AS created_by
FROM tm1_connections c
JOIN organizations o ON o.id = c.organization_id
JOIN users u ON u.id = c.created_by
ORDER BY o.name, u.email;
```

## 15. Security implications

- Closes cross-user visibility and use of TM1 connections within an
  organization, through the API, the UI and the AI tools.
- Non-disclosure preserved: unauthorized and missing look identical.
- Admins gain no credential access: they cannot test or run anything
  through a member's private connection.

## 16. Remaining limitations

- Sharing is all-or-nothing within an organization (no per-person or
  per-group sharing).
- Data already derived from a connection (change history, extraction
  history, health scans) is reachable only through that connection's
  routes, which are now guarded — but rows created before the fix are not
  re-attributed.
- The separate `planning_analytics_connections` model (MCP adapter) has
  the same organization-only scoping but no API or UI exposes it today;
  apply the same visibility rule before exposing it.
