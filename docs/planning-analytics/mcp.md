# IBM Planning Analytics MCP integration

> **DEVELOPER PREVIEW — never validated against a live IBM MCP server.**
> Tool discovery and risk classification are implemented. **No tool can
> be executed.**

PA-Copilot can optionally integrate with IBM Planning Analytics MCP
where the customer's environment, licensing, authentication and
configuration support it. It is not required, and most deployments will
not have it.

## What was verified from IBM sources

From [github.com/IBM/mcp](https://github.com/IBM/mcp) and IBM's
[April 2026 announcement](https://community.ibm.com/community/user/blogs/sami-el-cheikh1/2026/04/26/introducing-ibm-planning-analytics-assistant-mcp-s):

- An "IBM Planning Analytics MCP Server" exists, listed under Data &
  Analytics, and is a **remote** server.
- It **"Requires PA Agent feature addon entitlement"**.
- Access is "tied to the IBM Planning Analytics Assistant license".
- **OAuth** is the authentication mechanism.
- Four tool categories: **Modeling, Analysis, Workflow, Reporting**.
- Supported across PA Local, PA on Cloud, PA Certified Containers and
  PA as a Service.

## What could NOT be verified

**The individual tool names.** IBM's tool reference at
`ibm.com/docs/en/planning-analytics/3.1.0?topic=assistant-mcp-tools`
returns **HTTP 403** to unauthenticated requests, and the IBM/mcp
repository is a listing with no tool manifest.

This shaped the design rather than blocking it: **no tool list is
hard-coded**. The server is the runtime authority. `discover()` asks it
what it exposes; `risk.py` classifies whatever comes back; anything
unrecognised is `UNCLASSIFIED` and inert.

The announcement's four categories are used **only to group tools for
display**. They never influence risk.

## Entitlement is not authentication

A user can authenticate perfectly and still be refused, because IBM
gates MCP behind a licence. These are reported as different health
states:

| State | Meaning |
|---|---|
| `LICENSE_OR_ENTITLEMENT_REQUIRED` | Credentials fine; the licence is missing |
| `AUTHENTICATION_FAILED` | The credentials were rejected |

Collapsing them would send an administrator to reset a password that was
never wrong.

## Risk classification

Owned by the application, never by the model and never by the tool.

| Risk | Executable | Examples |
|---|---|---|
| `READ` | ✅ | `get_*`, `list_*`, `describe_*` |
| `ANALYSIS` | ✅ | `analyze_*`, `impact_*`, `detect_outliers` |
| `CONTROLLED_WRITE` | ❌ | `sandbox_*`, `checkout_*` |
| `WRITE` | ❌ | `create_*`, `execute_process`, `publish_*` |
| `DESTRUCTIVE` | ❌ | `delete_*`, `purge_*`, `reset_*` |
| `UNCLASSIFIED` | ❌ | anything unrecognised |

Three properties the tests enforce:

1. **`classify()` takes the tool name only.** There is no `description`
   parameter — a description claiming "safe, read-only" cannot influence
   the verdict, and a refactor adding one fails a test.
2. **Dangerous patterns are matched first.** `get_and_delete_view`
   classifies as `DESTRUCTIVE`, not `READ`.
3. **Unknown fails closed.** A tool IBM adds tomorrow is discovered,
   displayed, and not executable until a human classifies it.

## SSRF

The MCP endpoint is customer-supplied configuration, so PA-Copilot's own
backend will connect to whatever is stored. `ssrf.py` requires HTTPS and
**resolves DNS before deciding** — a hostname whose A record points at
`169.254.169.254` is caught, which a string check would miss.

Blocked: loopback, link-local (cloud metadata), private ranges,
reserved, multicast, and every non-HTTP scheme.

`allow_private_networks` exists for PA Local on an internal network. It
is an administrator deployment setting, never a per-request argument.
Loopback and link-local stay blocked even then.

**The LLM cannot supply an MCP URL** — no tool accepts one. Only an
administrator configures it.

**Known gap:** DNS can change between validation and connection
(TOCTOU). Closing it needs a pinned-IP connector; not done.

## Status on this deployment

**MCP LIVE VALIDATION BLOCKED.** No IBM MCP endpoint, no PA Assistant
entitlement, no OAuth configuration was available. Protocol handling is
tested against a mock server; **no mocked result may be cited as IBM
compatibility.**
