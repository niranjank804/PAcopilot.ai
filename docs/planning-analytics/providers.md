# Planning Analytics providers

> **DEVELOPER PREVIEW.** Native TM1 REST is the only validated
> integration. Everything else on this page is an optional adapter that
> has not been proven against a live environment.

PA-Copilot is not an IBM product and is not endorsed, certified or
approved by IBM. It is a governance and orchestration layer that can
integrate with several Planning Analytics interfaces.

## The four interfaces are genuinely different products

Conflating any two of these produces wrong answers about licensing,
where code runs, and what a failure means.

| Interface | What it is | Where it runs | Licence |
|---|---|---|---|
| **Native TM1 REST** | TM1's own HTTP API | PA-Copilot cloud | Included with Planning Analytics |
| **IBM PA MCP** | IBM's remote MCP server for agents | IBM-hosted, called from PA-Copilot | **Separate** — PA Assistant / PA Agent addon |
| **PAx** | IBM's COM automation API | *Inside a Windows Excel process* | Included with PAfE |
| **PAfE worker** | PA-Copilot's own Windows worker | Customer's Windows machine | Requires PAfE installed |

### PAx cannot be a cloud provider

This is a structural finding from this phase, not a scheduling decision.
The PAx API is a COM interface obtained from a running Excel instance
(`Application.COMAddIns(...).Object.AutomationServer`). It has no network
protocol and no out-of-process form. A cloud service cannot call it at
all — any "PAx adapter" in the control plane would be fiction.

PAx therefore belongs to the **worker**, alongside PAfE, and is
registered as `PLANNED` rather than implemented cloud-side.

## Capability layer

An agent asks for a *capability*, never a transport:

```
list_cubes  →  router  →  [ TM1 REST | IBM MCP ]  →  normalized result
```

Routing is **deterministic application code** (`registry.py`). The model
is never asked "should I use MCP?". Two consequences:

- Provider choice cannot be influenced through the conversation, which
  it could be if an LLM made the decision.
- Every result carries `source_reference`, stamped by the adapter that
  actually ran. An answer cannot claim IBM MCP produced something TM1
  REST did.

Priority: `TM1_REST (10) < IBM_MCP (50) < PAX / PAFE_WORKER (90)`. Lower
wins. If no configured provider declares a capability, the router
returns nothing rather than substituting one with different semantics.

## Read-only by construction

`PlanningAnalyticsCapability` contains no write member — no
`execute_process`, no `create_view`, no `write_cells`. A capability that
does not exist cannot be routed, requested, or enabled by configuration.

Discovered tools are classified by `risk.py` and only `READ` and
`ANALYSIS` are executable. Write, destructive, controlled-write and
unclassified tools are discovered, displayed, and blocked.

## Files

| File | Purpose |
|---|---|
| `capabilities.py` | Capability, provider and health enums |
| `risk.py` | Risk classification — application-owned |
| `ssrf.py` | Endpoint validation for customer-supplied URLs |
| `base.py` | Provider contract + the single authorization gate |
| `registry.py` | Provider classes + deterministic routing |
| `mcp_adapter.py` | IBM MCP protocol client, discovery, normalization |
| `results.py` | Provider-neutral result with provenance |
