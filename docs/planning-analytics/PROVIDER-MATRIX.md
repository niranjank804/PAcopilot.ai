# Provider decision matrix

Status key: **V** = live-verified · **I** = implemented, not live-verified ·
**P** = planned · **✗** = not applicable · **?** = unknown, needs live test

> Nothing in the IBM MCP column is verified. No live IBM MCP environment
> was available, and IBM's tool reference is 403-gated to unauthenticated
> requests, so its tool list is unknown. Every `?` below is an honest
> unknown, not a placeholder for "probably yes".

## Capability by provider

| Capability | TM1 REST | IBM MCP | PAfE worker | PAx | Recommended |
|---|---|---|---|---|---|
| List cubes | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Cube metadata | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Dimension metadata | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Element lists | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Read-only MDX | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Process metadata | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Dependency / impact graph | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Security group read | **V** | ? | ✗ | ✗ | **TM1 REST** |
| Rule / TI drafting (STET) | **V** | ✗ | ✗ | ✗ | **TM1 REST** |
| Excel workbook refresh | ✗ | ✗ | **I** | **I** | **PAfE worker** |
| Report artifact (XLSX/PDF) | ✗ | ✗ | **I** | ✗ | **PAfE worker** |
| Outlier detection | ✗ | ? | ✗ | ✗ | **unknown — test** |
| Async process execution | ✗ (sync only) | ? | ✗ | ✗ | **unknown — test** |
| Sandbox management | ✗ | ? | ✗ | ✗ | **out of scope (write)** |
| NL cube exploration | partial (via agent) | ? | ✗ | ✗ | **unknown — test** |

## What this shows

**Every capability PA-Copilot currently ships is already validated on
TM1 REST.** There is no capability in the product today that MCP would
unblock. Adding MCP for those would replace a working, licence-free,
low-latency integration with an unproven, separately-licensed one.

**The interesting column is the bottom four rows.** IBM advertises
outlier detection, impact analysis, async process execution and
natural-language cube exploration. Three of those are things TM1 REST
does not do natively and PA-Copilot currently approximates with its own
agent plus MDX. If IBM's implementations are good, that is real,
non-redundant value — and it is exactly what a live test must measure.

**PAx and PAfE are not alternatives to either.** They are the only route
to an Excel workbook refresh, which neither TM1 REST nor MCP can do.
They are complementary, not competing.

## Comparison rules

Comparing providers is only meaningful under conditions this phase could
not create:

1. **Same user, same permissions.** MCP authenticates via OAuth against
   the PA Assistant licence; TM1 REST uses stored TM1 credentials. If
   the two identities have different rights, "MCP returned more cubes"
   measures entitlement, not capability.
2. **Same semantic question.** "List cubes" must mean the same thing on
   both sides. IBM's tool names are unpublished, so this cannot yet be
   established.
3. **Both return data ≠ equivalence.** Record result counts, ordering
   and null handling before claiming parity.

Until those hold, the matrix records `?` rather than a guess.
