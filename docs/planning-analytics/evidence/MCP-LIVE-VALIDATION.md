# IBM MCP live validation — evidence record

**Result: `MCP LIVE VALIDATION BLOCKED`**
**Date:** 2026-08-13 · **Commit:** `e3b63af`

No benchmark was run. No capability was scored. Nothing in this document
is inferred, and the sibling documents this phase asked for
(`MCP-TOOL-INVENTORY.md`, `MCP-BENCHMARK.md`, `MCP-VALUE-DECISION.md`)
**deliberately do not exist** — creating them empty would be scaffolding
that reads like evidence.

## Prerequisites checked

Each was tested, not assumed.

| # | Prerequisite | Required | Found | Result |
|---|---|---|---|---|
| 1 | IBM Planning Analytics version | **3.1+** | **11.0.00100.927** | ❌ **FAIL** |
| 2 | PA Agent / PA Assistant entitlement | required | none | ❌ FAIL |
| 3 | MCP server endpoint | reachable URL | none configured | ❌ FAIL |
| 4 | OAuth configuration | issuer + client | absent | ❌ FAIL |
| 5 | Configured `PlanningAnalyticsConnection` | ≥1 `ibm_mcp` | **0 rows** | ❌ FAIL |
| 6 | A usable PA model | ≥1 | Planning Sample, 75 cubes | ✅ pass |

### The decisive one is #1

IBM ties the Planning Analytics MCP Server to **PA 3.1+**. The only
Planning Analytics instance available reports product version
**11.0.00100.927** — the PA 2.0 / TM1 11 line. The MCP server does not
exist in this product version, so items 2–5 cannot be satisfied by
configuration alone. This is not a missing setting; it is a missing
product generation.

Verified by direct query against the live server:

```
TM1 product version: 11.0.00100.927
server name:         Planning Sample
```

### What was ruled out

- **No MCP endpoint env vars.** (`MCP_CONNECTION_NONBLOCKING` is present
  but belongs to the local tooling, not IBM.)
- **No persisted MCP connection** — `planning_analytics_connections`
  returns zero rows for every provider.
- **Nothing MCP-shaped listening locally.** Port 3000 was probed with a
  JSON-RPC `initialize` and returned HTML — it is a Next.js dev server.

## What this does and does not mean

**Does not mean:** IBM MCP is unavailable, weak, or not worth using.
Nothing about IBM's implementation was measured. Any claim in either
direction would be fabricated.

**Does mean:** the four target capabilities — outlier detection, impact
analysis, async process execution, natural-language cube exploration —
remain unmeasured, and PA-Copilot must continue to treat IBM MCP as
`DEVELOPER_PREVIEW` and describe it as optional.

## The harness is ready

No further architecture is needed to obtain this evidence. Already built
and tested:

- `PlanningAnalyticsConnection` with org scoping and encrypted credentials
- MCP JSON-RPC client — `initialize`, `tools/list`, `tools/call`
- Runtime tool discovery with no hard-coded tool list
- Application-owned risk classification; unknown tools fail closed
- SSRF validation incl. redirect refusal
- Entitlement failure distinguished from authentication failure

## To unblock

1. Obtain access to **PA 3.1+** (Local, on Cloud, Certified Containers,
   or PAaaS) with the **PA Agent / PA Assistant** entitlement.
2. Configure OAuth and create an `ibm_mcp` connection.
3. Run discovery — the real `tools/list` is the authoritative inventory.
4. Benchmark **only** the four non-overlapping capabilities. Everything
   else is already validated on TM1 REST and would waste the environment.

Estimated effort once an environment exists: **one afternoon.**

## Regression at this commit

`1004` backend tests · `80` worker tests · zero failures. No code was
changed in this phase.

> The phase brief cites a 984-test baseline. That figure predates Phase
> 1.7, which added 20 connection-tenancy tests. 1004 is the correct
> current baseline; no test was removed, skipped or weakened.
