# Tool gap analysis — PA-Copilot vs a direct MCP connection

**Conclusion: every gap is closed except process execution, which is refused
by design.**

PA-Copilot started this analysis at **25 tools** against a direct MCP server's
**67 read-only tools**. It now exposes **42**, and the comparison has changed
shape: the remaining difference is not capability but *kind*. MCP retrieves;
PA-Copilot retrieves **and analyses**.

| | Start | Final |
|---|---|---|
| Tools | 25 | **42** |
| Capability areas absent | 3 | **0** |
| Areas ahead of MCP | 3 | **8** |

Three capabilities now have no MCP equivalent at all: `audit_model_rules`,
`run_model_health_check`, and `map_log_error_to_code`. Each composes work that
a retrieval surface can only reach by looping, which in practice means nobody
reaches it.

## Method

The PA-Copilot inventory is exact: every tool declares `name = "..."` in
`backend/src/ai/tools/`, and all 42 are listed below. Nothing is inferred from
the landing page.

The 67-tool figure and its capability breakdown come from a **screenshot of a
working session**, not from inspecting that server's source. The categories are
quoted as reported. Individual tool names on that side were not enumerated, so
this document compares **capability areas**, not tool-to-tool.

## The PA-Copilot inventory

| Module | Tools |
|---|---|
| `tm1/analysis.py` | `find_dependents`, `find_dependencies`, `dependency_path`, `find_unused_objects` |
| `tm1/metadata.py` | `get_cube_dependencies`, `get_dimension_dependents`, `get_object_relationships` |
| `tm1/cubes.py` | `list_cubes`, `get_cube`, `get_cube_rules` |
| `tm1/dimensions.py` | `list_dimensions`, `get_dimension`, `list_dimension_elements` |
| `tm1/processes.py` | `list_processes`, `get_process` |
| `tm1/chores.py` | `list_chores`, `get_chore` |
| `tm1/cells.py` | `execute_mdx` |
| `tm1/functions.py` | `lookup_tm1_function`, `check_tm1_code` |
| `tm1/standards.py` | `get_coding_standards` |
| `tm1/changes.py` | `propose_rule_update`, `propose_process_update`, `propose_process_copy` |
| `knowledge.py` | `search_knowledge_base` |
| `tm1/logs.py` *(new)* | `get_message_log`, `get_transaction_log`, `list_process_error_logs`, `get_process_error_log`, `map_log_error_to_code` |
| `tm1/rules.py` *(new)* | `analyze_cube_rules`, `trace_cell_calculation`, `search_rules`, `audit_model_rules` |
| `tm1/structure.py` *(new)* | `list_cube_views`, `list_dimension_subsets`, `get_dimension_attributes`, `get_element_context`, `get_server_state` |
| `tm1/health.py` *(new)* | `run_model_health_check` |
| `tm1/processes.py` *(added)* | `search_process_code`, `diff_process` |

**42 total.** 39 read, 3 propose. No tool executes anything — see gap 3.

## The comparison

| Capability area | MCP | PA-Copilot | Verdict |
|---|---|---|---|
| Diagnostics / logs | message, transaction, audit logs; per-process `.log`; error-line → code-line | 5 tools incl. `map_log_error_to_code` (one call) | **PA-Copilot ahead** |
| Code search | search all 437 processes; diff two processes | `search_process_code` + `diff_process` | **Parity** |
| Feeders | audit and trace feeders; trace a cell's calculation and data flow | static analyser + 4 tools, incl. model-wide audit | **PA-Copilot ahead** |
| Model structure | subsets, views, attributes, hierarchies, default members | all of those, plus composite `get_element_context` | **PA-Copilot ahead** |
| Server state | version, threads, sessions, clients, groups | `get_server_state` | **Parity** |
| Impact analysis | writes-to-cube, `ExecuteProcess` call tree, chore map | 6 dedicated tools + chores | **PA-Copilot ahead** |
| Data / MDX | `execute_mdx` | `execute_mdx` + charting | **PA-Copilot ahead** |
| Standards grounding | external (local skills) | `get_coding_standards`, `search_knowledge_base`, `lookup_tm1_function` | **PA-Copilot ahead** |
| Writes | 47 direct tools behind a mode flag | 3 `propose_*` + snapshot / verify / rollback | **Better design, narrower scope** |
| Model sweeps | naming, complexity, v12 readiness | `run_model_health_check` (rules + TI, ranked) | **PA-Copilot ahead** |

## Gap 1 — the loop does not close: CLOSED

**Resolved by `tm1/logs.py`.** The agent now reads the message log, the
transaction log and a failed process's own error log, and resolves logged
errors back to the exact line of code. One manual step remains — a human
runs the process — which is deliberate; see gap 3.

The original finding, for the record:

PA-Copilot can draft a fix. It cannot run it, and it cannot read what happened.
There is no execute tool and no log tool. So the developer loop:

```
describe the problem -> draft a fix -> save it -> run it -> read the log -> see what broke
                                          |
                                   PA-Copilot stops here
```

Everything after `save` happens in PAW, by hand, outside the product. The
developer then returns and pastes the error into chat, where "Explain Error"
reasons over text the human had to go and fetch.

The MCP session closes that loop, and that is the whole reason it measured a
~90% reduction in investigation time on real PBI work. **The value is in the
loop, not in any single step of it.**

## Gap 2 — no code search: CLOSED

**Resolved by `search_process_code` and `diff_process`.** Matching is pushed
down to the server rather than fetching every process.

The original finding, for the record:

`get_process` retrieves one process by name. There is no way to answer:

- which of the 437 processes reference this cube
- which processes contain `CELLPUTN`
- what changed between this Dev process and my local copy

These are daily questions for a TM1 developer, and the only path was fetching
processes one at a time, which does not scale past a handful.

## Gap 3 — feeders: CLOSED, and now ahead of MCP

**Originally:** the product headlined "Rules & Feeders Intelligence" while the
registry contained `get_cube_rules` and nothing feeder-specific. Feeder
reasoning was inference over rule text — fine on the three-line demo cube,
unreliable on a real model.

**Now:** `src/tm1/rules/` parses rule text into statements and runs seven
deterministic checks over it. Four tools expose it:

| Tool | Answers |
|---|---|
| `analyze_cube_rules` | Are this cube's rules and feeders correct? |
| `trace_cell_calculation` | Why does *this* intersection have *that* value? |
| `search_rules` | Which cubes reference X in a rule? (server-side) |
| `audit_model_rules` | Which cubes in the whole model have problems? |

Checks: unfed calculation under `SKIPCHECK`, `SKIPCHECK` with no `FEEDERS`
section, feeders without `SKIPCHECK`, statements stranded below the `FEEDERS`
marker, shadowed areas, feeders targeting uncalculated areas, and string rules
without `FEEDSTRINGS`.

**This is a different class of capability from the MCP surface.** MCP's 67
tools retrieve; the model reasons over what comes back. These compute. The
same rule file produces the same findings every time, with line numbers, at
any rule size — which is exactly where text reasoning degrades.

`audit_model_rules` has no MCP equivalent at all: one call analyses every cube
carrying a rule, concurrently, and returns them ranked worst-first. Reaching
the same answer through a retrieval surface means the model looping cube by
cube across dozens of round trips.

The false-positive stance follows `deployment/ti_analysis.py`: a calculation
counts as fed when its area shares any element with any feeder target, and a
rule containing feeder targets that cannot be resolved statically (`DB(...)`)
downgrades the unfed finding from critical to warning and says why.

## Where PA-Copilot leads

Not consolation. These are real and the MCP setup cannot match them.

| Area | Why it wins |
|---|---|
| **Dependency analysis** | Six purpose-built tools against a descriptive capability on the MCP side. More structured, and already the strongest part of the product. |
| **Knowledge grounding** | `search_knowledge_base` + `get_coding_standards` ship to customers. Local skills do not. |
| **Write architecture** | Snapshot -> write -> verify -> auto-restore is a mechanism. "Two people agree to flip a setting" is a policy. Policies fail quietly. |
| **Governance** | RBAC, per-org scoping, audit log, human diff review. Structurally unavailable to a single-user MCP session. |
| **Surface** | Charting, multimodal, voice, PAfE report scheduling. |

## What was built

### 1. Log tools — closes the loop

New module `backend/src/ai/tools/tm1/logs.py`:

| Tool | Returns |
|---|---|
| `get_message_log` | server message log, filtered by time window and severity |
| `get_transaction_log` | cell-change history for a cube and time window |
| `get_process_log` | the `.log` file a named process run produced |
| `map_log_error_to_code` | a message-log error line resolved to the process and line that raised it |

`map_log_error_to_code` is the demo that lands with TM1 developers, because
every one of them knows how long it takes by hand.

Respect the existing response caps — logs are unbounded and a naive
implementation will blow the context window on the first busy morning.

### 2. `search_process_code` — cheapest high-value addition

Extends `backend/src/ai/tools/tm1/processes.py`:

- substring or regex across all process code, all four tabs
- returns process name, tab, line number, matching line
- capped result count, same convention as `list_dimension_elements`

A `diff_process` companion (Dev against a supplied file) is a natural sibling
and reuses the same fetch path.

### 3. Execute-with-approval — NOT RECOMMENDED without a deliberate decision

The obvious completion of the loop is a `run_process` change type: the agent
proposes a run, a permitted human confirms it as they would a write, and the
platform fetches the resulting log.

**It was drafted and then reverted, because the codebase already rejects it on
purpose.** `src/planning_analytics/capabilities.py` states:

> There is deliberately no `execute_process`, `create_view`, `write_cells` or
> `publish_report` member. A capability that does not exist cannot be routed,
> requested, or accidentally enabled by configuration — the absence is the
> control.

That is a stronger security posture than any approval gate, and it is the same
argument this document makes in favour of PA-Copilot's write design over the
MCP mode flag. Adding process execution would trade it away.

The trade, stated plainly:

| Keep the absence | Add `run_process` |
|---|---|
| No code path can execute anything, however misconfigured | A gated path exists, and gates can be misconfigured |
| The loop stays open: a human runs the process in PAW | The loop closes inside the product |
| Gap 1 still delivers most of the value — the agent reads the log afterwards | Faster, at the cost of the strongest control in the system |

**Recommendation: do not add it as a side effect of closing a gap.** With gap 1
in place the agent can already read what happened after a human runs the
process manually, which recovers most of the benefit and none of the risk. If
execution is wanted later it should be an explicit, separately reviewed
decision — with the capability enum, the risk classifier in
`src/planning_analytics/risk.py`, rollback behaviour (a run has no inverse) and
the customer-facing security claims all revisited together.

## What is not addressed here

**Identity propagation.** PA-Copilot's RBAC is enforced in the application over
what appears to be one TM1 connection per organization. TM1 cannot distinguish
a Planner from an Analyst; PA-Copilot decides and TM1 executes as the
connection. That is the normal SaaS pattern and is out of scope for a tool gap
analysis, but it is the question an enterprise security review will ask, and
[AB#4055969](../../../) is a live example of TM1-side security mattering.

**Relative quality.** This compares presence and absence of capability. It does
not measure whether PA-Copilot's `find_dependents` is better or worse than the
MCP equivalent, because the MCP tool list was never enumerated.
