# TM1 capability gap matrix

Benchmark: the 114 capabilities in the PA-Copilot Enterprise TM1 brief (2026-09-24), modelled on a Claude + MCP + TM1 REST setup. Every row was classified by reading the implementation, not the tool name.

**Baseline** is the repository as found on 2026-09-24, including uncommitted work from 2026-09-23 (17 read tools in `backend/src/ai/tools/tm1/{logs,rules,structure,health}.py`). That work was implemented and unit-tested but on no specialist agent's allowlist, so no agent could call it. Rows depending on it are PARTIAL at baseline for that reason.

## Summary

| Status | Baseline |
|---|---|
| EXISTS | 40 |
| PARTIAL | 52 |
| MISSING | 22 |
| BLOCKED_BY_TM1_API | 0 |
| REQUIRES_CUSTOMER_CONNECTOR | 0 |
| NOT_APPLICABLE | 0 |

Paths are relative to `backend/src/` unless they start with a frontend route. `tools/tm1` means `backend/src/ai/tools/tm1`. Test files are under `backend/tests/`.

Security for every row: organization isolation through `tm1_integration_service.get_connection(db, id, organization_id)`, the per-tool permission re-check inside `Tool.execute`, the connection's circuit breaker, TM1py's request timeout, and the tool-execution audit row. Rows with a class other than READ add the controls in their own cell.


## A. TM1 Model Discovery

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 1 | TM1 server connection | EXISTS | `diagnose_connection` classifies credentials_rejected / not_found / unreachable; SSRF policy on save | Connections page: Test | None | tm1.read (test), tm1.write (save) | READ | tests/unit/tm1/test_service.py, test_address_policy.py |
| 2 | Server information | PARTIAL | `get_server_state` (tools/tm1/structure.py): version, sessions, threads. Registered, on no agent's allowlist, no UI | — | Add to Administrator, Performance, Troubleshooter | tm1.read | READ | test_structure_tools.py |
| 3 | Cubes | EXISTS | `list_cubes` → tm1/service.py → cube_service | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py, test_tm1_api.py |
| 4 | Cube dimensions | EXISTS | `get_cube` returns the cube's dimensions | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py |
| 5 | Dimension order | EXISTS | `get_cube` keeps TM1's dimension order (list, not set) | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_cube_service.py |
| 6 | Dimensions | EXISTS | `list_dimensions`, `get_dimension` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py |
| 7 | Dimension elements | EXISTS | `list_dimension_elements` (capped, per hierarchy) | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py |
| 8 | Element attributes | PARTIAL | `get_dimension_attributes` returns definitions only; no values | — | `get_element_context` also reads the element's attribute VALUES from the `}ElementAttributes_<dim>` control cube | tm1.read | READ | test_structure_tools.py |
| 9 | Hierarchies | EXISTS | `get_dimension` lists hierarchies; `get_dimension_attributes` adds default member | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_structure_tools.py |
| 10 | Alternate hierarchies | EXISTS | `hierarchy_name` accepted by element, subset and attribute tools | — | None | tm1.read | READ | test_structure_tools.py |
| 11 | Subsets | PARTIAL | `list_dimension_subsets`: public names only | — | New `get_subset`: MDX expression or static elements (capped) | tm1.read | READ | test_structure_tools.py |
| 12 | Views | PARTIAL | `list_cube_views`: names only | — | New `get_view`: MDX for MDX views, generated MDX for native views | tm1.read | READ | test_structure_tools.py |
| 13 | Processes | EXISTS | `list_processes` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py |
| 14 | Process details | EXISTS | `get_process` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_process_tools.py |
| 15 | Process parameters | PARTIAL | `get_process` returns parameter names only | Connection detail (`connections/[id]`) | Return name, type, default value and prompt | tm1.read | READ | test_process_tools.py |
| 16 | Process data sources | PARTIAL | type, name, view only | Connection detail (`connections/[id]`) | Add variables and ASCII settings | tm1.read | READ | test_process_tools.py |
| 17 | Process tabs / code | EXISTS | `get_process` returns Prolog/Metadata/Data/Epilog (truncated for the model) | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_process_tools.py |
| 18 | Chores | EXISTS | `list_chores`, `get_chore` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_chore_tools.py |
| 19 | Chore schedules | MISSING | `get_chore` returns active flag and processes only | Connection detail (`connections/[id]`) | Add start time, frequency, execution mode, per-step parameters | tm1.read | READ | test_chore_tools.py |
| 20 | Rules | EXISTS | `get_cube_rules` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_tools.py |
| 21 | Feeders | PARTIAL | Static feeder analysis (`analyze_cube_rules`, src/tm1/rules/). Runtime feeder state ("is this cell fed?") is not exposed by TM1 REST | — | Keep static; label runtime feeder checks UNKNOWN | tm1.read | READ | test_rule_analysis.py |
| 22 | Control dimensions | MISSING | `skip_control_dims=True` hard-coded | — | `include_control` flag on `list_dimensions` | tm1.read | READ | — |
| 23 | Control cubes | MISSING | `skip_control_cubes=True` hard-coded | — | `include_control` flag on `list_cubes` | tm1.read | READ | — |
| 24 | TI metadata | PARTIAL | `get_process` + TI parser (src/tm1/ti/parser.py) used only by standards learning | — | New `analyze_process_references`: cubes read/written, dimensions, processes called, from the parser, live | tm1.read | READ | test_ti_parser.py |
| 25 | Application / model metadata | PARTIAL | Metadata graph (cubes, dimensions, hierarchies, processes, chores). TM1 Applications folder not read | Metadata explorer (`metadata`) | Extend graph (see §B, §11). Applications remain out of scope | tm1.read / tm1.write (extract) | READ | test_extractor.py |

## B. Model Exploration

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 26 | Find cube | PARTIAL | Model lists all names and filters in context | — | New `search_model_objects` (name substring, server-side where TM1 supports it) | tm1.read | READ | — |
| 27 | Find dimension | PARTIAL | as 26 | — | `search_model_objects` | tm1.read | READ | — |
| 28 | Find element | MISSING | Exact name only (`get_element_context`); element list is capped | — | `search_model_objects` element mode → TM1py `get_elements_filtered_by_wildcard` (server-side OData filter) | tm1.read | READ | — |
| 29 | Find process | PARTIAL | as 26 | — | `search_model_objects` | tm1.read | READ | — |
| 30 | Find view | PARTIAL | Per cube only | — | `search_model_objects` view mode (per cube) | tm1.read | READ | — |
| 31 | Find subset | PARTIAL | Per dimension only | — | `search_model_objects` subset mode (per dimension) | tm1.read | READ | — |
| 32 | Find rule | EXISTS | `search_rules` (server-side) | — | None | tm1.read | READ | test_rule_tools.py |
| 33 | Find feeder | PARTIAL | `search_rules` matches feeder text; `analyze_cube_rules` lists feeder statements | — | None beyond agent access | tm1.read | READ | test_rule_tools.py |
| 34 | Search model objects | MISSING | — | — | `search_model_objects` across cubes, dimensions, processes, chores (+ elements/views/subsets when scoped) | tm1.read | READ | — |
| 35 | Search process code | EXISTS | `search_process_code` (server-side contains filter, line-level hits) | — | Agent access | tm1.read | READ | test_process_tools.py |
| 36 | Search rules | EXISTS | `search_rules` | — | Agent access | tm1.read | READ | test_rule_tools.py |
| 37 | Search metadata | PARTIAL | Graph lookups need an exact name | Metadata explorer (`metadata`) | `search_model_objects` covers names; graph stays exact-match | tm1.read | READ | — |
| 38 | Inspect object dependencies | EXISTS | `find_dependencies`, `find_dependents`, `dependency_path` (needs metadata extraction) | Metadata explorer (`metadata`) | Richer edges (§11) | tm1.read | READ | test_dependency_analyzer.py |
| 39 | Where an object is referenced | PARTIAL | Graph lacks process→process, CellGet reads, dimension writes; text search is separate | Metadata explorer (`metadata`) | Extractor uses the TI parser (calls_process, reads_cube, updates_dimension, uses_dimension) | tm1.read | READ | test_extractor.py |
| 40 | What writes to a cube | PARTIAL | `updates_cube` edges from a regex; no dedicated tool; extraction required | Metadata explorer (`metadata`) | New `get_cube_data_flow`: graph when extracted, live parse otherwise; chores that run the writers | tm1.read | READ | — |
| 41 | What reads from a cube | PARTIAL | Only TM1CubeView datasources and rule `DB()` references | Metadata explorer (`metadata`) | `get_cube_data_flow` adds CellGet readers | tm1.read | READ | — |

## C. Cell / Cube Analysis

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 42 | Read cube cell | PARTIAL | Only by writing MDX | — | New `get_cell_values` (coordinates → values, TM1py `cells.get_values`) | tm1.read | READ | — |
| 43 | Read multiple cells | PARTIAL | as 42 | — | `get_cell_values` (≤ 50 coordinates) | tm1.read | READ | — |
| 44 | Execute MDX | EXISTS | `execute_mdx` (read-only, capped) | Visualize, chat | None | tm1.read | READ | test_cell_service.py |
| 45 | Structured MDX results | EXISTS | Element-path → value map | Visualize | None | tm1.read | READ | test_cell_service.py |
| 46 | Inspect calculated cell | PARTIAL | `trace_cell_calculation` is static only | — | New `inspect_cell`: value plus TM1's own RuleDerived / Consolidated / Updateable flags (VERIFIED), plus the static rule trace (labelled) | tm1.read | READ | — |
| 47 | Explain cell calculation | PARTIAL | static trace | — | `inspect_cell` combines TM1 flags with the static trace | tm1.read | READ | test_rule_tools.py |
| 48 | Trace rule dependencies | PARTIAL | `references_cube` edges from `DB()`; static rule parse | Metadata explorer (`metadata`) | None beyond agent access | tm1.read | READ | test_rule_analysis.py |
| 49 | Identify contributing rules | PARTIAL | `trace_cell_calculation` returns the applying statement | — | via `inspect_cell` | tm1.read | READ | test_rule_tools.py |
| 50 | Feeder relationships | PARTIAL | static only | — | Runtime feeder evidence is not in TM1 REST → UNKNOWN | tm1.read | READ | test_rule_analysis.py |
| 51 | Compare cell values | MISSING | — | — | `get_cell_values` returns all requested coordinates together with differences | tm1.read | READ | — |
| 52 | Export analytical results | PARTIAL | Charts on Visualize; no file export | Visualize | Not in this change | tm1.read | READ | — |
| 53 | Missing / invalid intersections | MISSING | — | — | `get_cell_values` checks every element exists before reading and names the bad coordinate | tm1.read | READ | — |

## D. Process Diagnostics

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 54 | Read TI process | EXISTS | `get_process` | Connection detail (`connections/[id]`) | None | tm1.read | READ | test_process_tools.py |
| 55 | Read process log | PARTIAL | `get_process_error_log`, `list_process_error_logs` (tools/tm1/logs.py). On no agent | — | Agent access | tm1.read | READ | test_log_tools.py |
| 56 | Read message log | PARTIAL | `get_message_log`. On no agent | — | Agent access | tm1.read | READ | test_log_tools.py |
| 57 | Transaction / audit information | PARTIAL | `get_transaction_log`. TM1 audit log (needs AuditLog=T on the server) not read | — | Agent access; audit log stays out | tm1.read | READ | test_log_tools.py |
| 58 | Process execution status | MISSING | — | — | New `get_process_execution_history`: runs recorded in the message log (TM1.Process logger), with outcome where TM1 wrote one | tm1.read | READ | — |
| 59 | Process statistics | MISSING | — | — | TM1 REST has no per-process statistics entity. Elapsed time is parsed from the message log where present; a customer 'Process Stats' cube needs a customer mapping | tm1.read | READ | — |
| 60 | Process end time | MISSING | — | — | `get_process_execution_history` returns the log timestamp of each finish/abort line | tm1.read | READ | — |
| 61 | Identify failed process | PARTIAL | `list_process_error_logs` across all processes | — | Agent access; execution history marks aborted runs | tm1.read | READ | test_log_tools.py |
| 62 | Identify error location | PARTIAL | `map_log_error_to_code`. On no agent | — | Agent access | tm1.read | READ | test_log_tools.py |
| 63 | Correlate failure with logs | MISSING | — | — | New `diagnose_process_failure`: process + latest error log mapped to code + message-log entries + execution history + references, each labelled VERIFIED / UNKNOWN | tm1.read | READ | — |
| 64 | Process dependencies | PARTIAL | Graph (extraction required) | Metadata explorer (`metadata`) | `analyze_process_references` (live) | tm1.read | READ | — |
| 65 | Process call tree | MISSING | TI parser extracts ExecuteProcess callees; nothing exposes it | — | New `get_process_call_tree` (live, bounded depth and node count); `calls_process` graph edges | tm1.read | READ | — |
| 66 | Explain failure | PARTIAL | `/knowledge/explain-error` over pasted text | Knowledge page | Troubleshooter explains from `diagnose_process_failure` evidence | ai.chat + tm1.read | READ | — |
| 67 | Propose fix | EXISTS | `propose_process_update` draft | Deployments (`deployments`) + chat change card | None | tm1.write | WRITE (draft) | test_change_tools.py |
| 68 | Validate proposed fix | EXISTS | Static analysis + server compile dry-run at draft creation | Deployments (`deployments`) + chat change card | Standalone `validate_process_code` | tm1.read | VALIDATE | test_change_service.py |
| 69 | Compile without saving | PARTIAL | `compile_process_dryrun` used inside draft creation only | — | `validate_process_code` exposes it (TM1 `/CompileProcess`, unsaved) | tm1.read | VALIDATE | test_change_service.py |

## E. TI Development

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 70 | Generate TI process | EXISTS | TI / Developer agents + `propose_process_update` | Chat | None | tm1.write | WRITE (draft) | test_change_tools.py |
| 71 | Modify existing TI | EXISTS | `propose_process_update` (update) | Chat | None | tm1.write | WRITE (draft) | test_change_tools.py |
| 72 | Explain TI | EXISTS | Agent over `get_process` (AI interpretation) | Chat | None | tm1.read | READ | — |
| 73 | Review TI | PARTIAL | Reviewer agent + `check_tm1_code`; no structured findings | Chat | New `review_process_code`: findings with severity, object, evidence, reason, recommendation, confidence | tm1.read | READ | — |
| 74 | Detect unsupported TI functions | EXISTS | `check_tm1_code` against src/tm1/functions/tm1_functions.json | Chat | None | tm1.read | READ | test_functions.py |
| 75 | Detect syntax issues | PARTIAL | Server compile at draft time; `ti_analysis` undefined names / case | — | `validate_process_code` returns both | tm1.read | VALIDATE | test_ti_analysis.py |
| 76 | Detect dangerous operations | MISSING | — | — | `review_process_code` flags destructive TI calls (CubeClearData, DimensionDeleteAllElements, ExecuteCommand, …) from a fixed list | tm1.read | READ | — |
| 77 | Analyze complexity | PARTIAL | — | — | `review_process_code` metrics: statements, loops, nesting, calls | tm1.read | READ | — |
| 78 | Analyze naming | PARTIAL | Conventions learned (`get_coding_standards`); nothing compares a process to them | — | `review_process_code` checks variable prefixes against learned conventions where confidence allows | tm1.read | READ | — |
| 79 | Analyze maintainability | MISSING | — | — | `review_process_code`: header comment, hard-coded literals, commented-out code | tm1.read | READ | — |
| 80 | Analyze compatibility | PARTIAL | `check_tm1_code(version=…)` | — | Included in `review_process_code` | tm1.read | READ | test_functions.py |
| 81 | v12 readiness | PARTIAL | `check_tm1_code(version='v12')` uses the reference's v12 flags | — | Included in `review_process_code` | tm1.read | READ | test_functions.py |
| 82 | Compile / validate without save | PARTIAL | draft-only | — | `validate_process_code` | tm1.read | VALIDATE | — |
| 83 | Reviewable diff | EXISTS | Draft diff view; `diff_process` | Deployments (`deployments`) + chat change card | None | tm1.read | READ | test_process_tools.py |

## F. Process Execution

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 84 | Execute process | MISSING | Deliberately absent (docs/planning-analytics/TOOL-GAP-ANALYSIS.md gap 3) | — | `run_process` change type in the STET pipeline: AI proposes, a person with tm1.execute approves and runs | tm1.execute | EXECUTE | — |
| 85 | Execute with parameters | MISSING | — | — | Parameters validated against the process's own parameter list and shown before approval | tm1.execute | EXECUTE | — |
| 86 | Monitor execution | MISSING | — | — | Synchronous run with TM1's own timeout; status recorded on the change. No live progress stream (TM1 REST returns at completion) | tm1.execute | EXECUTE | — |
| 87 | Retrieve execution result | MISSING | — | — | `execution_result` on the change: success, TM1 status, error-log file, duration | tm1.read | READ | — |
| 88 | Retrieve Process Stats | MISSING | — | — | See 59 | tm1.read | READ | — |
| 89 | Detect success / failure | MISSING | — | — | TM1 ExecuteWithReturn status (CompletedSuccessfully, Aborted, HasMinorErrors, …) mapped to executed / failed | tm1.execute | EXECUTE | — |
| 90 | Retrieve logs after execution | PARTIAL | Logs readable after a manual run | — | Error-log excerpt captured automatically on a failed run | tm1.read | READ | — |

## G. Process / Model Change Management

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 91 | Draft change | EXISTS | `change_service.create_change` | Deployments (`deployments`) + chat change card | Adds `run_process` | tm1.write | WRITE (draft) | test_change_service.py |
| 92 | Show diff | EXISTS | `get_change_preview` | Deployments (`deployments`) + chat change card | None | tm1.read | READ | test_changes_api.py |
| 93 | Validate change | EXISTS | static + compile dry-run at draft; validation errors block execution | Deployments (`deployments`) + chat change card | None | tm1.write | VALIDATE | test_change_service.py |
| 94 | Snapshot / baseline | EXISTS | `previous_content` captured at execute | Deployments (`deployments`) + chat change card | None | tm1.deploy | WRITE | test_change_service.py |
| 95 | Save approved change | EXISTS | `execute_change` | Deployments (`deployments`) + chat change card | None | tm1.deploy | WRITE | test_change_service.py |
| 96 | Execute approved process | MISSING | — | Deployments (`deployments`) + chat change card | `run_process` change | tm1.execute | EXECUTE | — |
| 97 | Verify result | PARTIAL | Server compile / rule check after apply, auto-restore on failure | Deployments (`deployments`) + chat change card | Run result recorded and verified from TM1's return status | tm1.deploy | WRITE | test_change_service.py |
| 98 | Rollback | EXISTS | `rollback_change` restores the snapshot | Deployments (`deployments`) + chat change card | A process run has no inverse: rollback refused with that reason | tm1.deploy | WRITE | test_change_service.py |
| 99 | Idempotency / fingerprint | EXISTS | `_fingerprint` + partial unique index on open drafts + row lock on transitions | Deployments (`deployments`) + chat change card | Fingerprint covers run parameters | — | — | test_change_locking.py |
| 100 | Audit complete lifecycle | EXISTS | audit_service on create / execute / reject / rollback | — | Tool executions also record agent and request id | — | — | test_changes_api.py |

## H. Development / Dev-vs-Local Workflows

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 101 | Compare TM1 process with a local file | PARTIAL | `diff_process` takes text; chat attachments accept images, PDF, DOCX only | — | Accept `.pro` / `.txt` / `.ti` attachments as text (controlled upload, no server filesystem) | tm1.read | READ | test_attachment_processing.py |
| 102 | Compare versions | PARTIAL | server vs supplied text; change snapshots hold previous versions | Deployments (`deployments`) + chat change card | None | tm1.read | READ | — |
| 103 | Generate diff | EXISTS | `diff_process` unified diff | — | None | tm1.read | READ | test_process_tools.py |
| 104 | Identify changed lines | EXISTS | Unified diff hunks carry line numbers | — | None | tm1.read | READ | test_process_tools.py |
| 105 | Validate local version | PARTIAL | `check_tm1_code` | — | `validate_process_code` + `review_process_code` on supplied text | tm1.read | VALIDATE | — |
| 106 | Compile against server | PARTIAL | draft-only | — | `validate_process_code` | tm1.read | VALIDATE | — |
| 107 | Show deployment impact | EXISTS | Draft impact analysis from the graph | Deployments (`deployments`) + chat change card | None | tm1.read | READ | test_change_service.py |

## I. Model Quality / Governance

| # | Capability | Baseline | Current implementation (backend) | Frontend | Required change | Permission | Class | Tests |
|---|---|---|---|---|---|---|---|---|
| 108 | Naming convention scan | PARTIAL | Conventions learned; no scan | Standards page | Per-process naming check in `review_process_code`; model-wide naming sweep not built | tm1.read | READ | — |
| 109 | Complexity scan | PARTIAL | — | — | `run_model_health_check` includes per-process complexity | tm1.read | READ | — |
| 110 | Compatibility scan | PARTIAL | per snippet | — | Health check runs the function-compatibility check per process | tm1.read | READ | — |
| 111 | Orphaned object detection | EXISTS | `find_unused_objects` (graph; says it is only as good as the extraction) | Metadata explorer (`metadata`) | None | tm1.read | READ | test_dependency_analyzer.py |
| 112 | Dependency analysis | EXISTS | graph tools | Metadata explorer (`metadata`) | Richer edges | tm1.read | READ | test_dependency_analyzer.py |
| 113 | Documentation completeness | MISSING | — | — | Health check flags processes with no header comment, parameters with no prompt | tm1.read | READ | — |
| 114 | Model health report | PARTIAL | `run_model_health_check`: rule findings + TI undefined-name issues; findings lack recommendation / confidence | — | Findings in one shape: severity, object, evidence, reason, recommendation, confidence | tm1.read | READ | — |

## Architecture findings (phase 1)

The path a TM1 question takes today, verified by reading the code:

```
POST /ai/chat/stream  (api/v1/ai.py; ai.chat + AI rate limit + model allowlist + quota)
  → ai_orchestrator.stream_chat          (ai/orchestrator.py; bounded tool loop, DB released per round)
  → persona allowlist                    (ai/prompts/<agent>.yaml `tool_names`; hard-rejected otherwise)
  → Tool.execute                         (ai/tools/…; each tool re-checks its own permission)
  → tm1_integration_service              (tm1/service.py; resolves the connection *within the caller's organization*)
  → tm1/services/*                       (thin TM1py wrappers)
  → call_with_resilience                 (tm1/resilience.py; bounded pool, TM1py timeout, retry, circuit breaker, sanitised errors)
  → TM1 REST
  ← ai_tool_executions row (arguments, status, duration, summary) + audit_logs on changes
```

| Area | What exists | Consequence for this work |
|---|---|---|
| Tool registry | `ai/tools/registry.py`: a dict of `Tool` subclasses with name, description, JSON schema, `required_permission` | Extend `Tool` with classification metadata; do not create a second registry |
| Agents | 9 YAML personas; the allowlist is the hard gate | New tools are useless until a persona lists them — 17 tools were in this state |
| Provider layer | `planning_analytics/` (base, registry, risk, MCP adapter). TM1 REST is *deliberately* not registered there | Keep TM1 REST on its validated direct path. No MCP provider is added: nothing in the benchmark needs one |
| Capability registry | `ai/capabilities.py` (AVAILABLE / DEVELOPER_PREVIEW / PLANNED / DISABLED / DEPRECATED), drives the assistant's product knowledge and has consistency tests | New capabilities are declared there, at DEVELOPER_PREVIEW until verified live |
| Change management | `tm1/deployment/change_service.py`: draft → static + compile dry-run → fingerprint → human execute (tm1.deploy) → snapshot → apply → compile/rule check → auto-restore → rollback; row-locked transitions; audited | Process execution becomes a `run_process` change type in this pipeline. No second pipeline |
| Metadata graph | `tm1_objects` / `tm1_relationships`, extractor + analyzer; process edges from a regex | Extractor switches to the existing TI parser (`tm1/ti/parser.py`), which already extracts reads, writes, calls and dimensions |
| TI analysis | `tm1/deployment/ti_analysis.py` (undefined names, case), `tm1/functions/tm1_functions.json` + `check_tm1_code` (existence, v12 validity), TI parser | Reused for review, validation, health findings |
| Logs | `tm1/services/log_service.py` (message log, transaction log, process error logs) | Reused for execution history and failure diagnosis |
| Frontend | Chat with tool timeline (name + status only), Deployments + shared `ChangeActionCard`, Metadata explorer, Connection detail tabs | Extend the timeline and the change card; no new page is needed for the benchmark |
| Voice | `frontend/src/lib/voice.ts`: speech-to-text → the same chat request → text-to-speech | Already uses the one orchestrator; nothing to duplicate |
| Execution posture | `planning_analytics/capabilities.py` has no execute capability, by design, and TOOL-GAP-ANALYSIS.md recommended keeping it absent | The brief is the explicit decision that document asked for. Execution is added only as an approved change: the model can propose a run and never perform one |

## Reusable components (phase 3)

| Need | Reused | New code |
|---|---|---|
| Process call tree, reads/writes | `tm1/ti/parser.py` `parse_process` | Tool wrapper + bounded traversal |
| Execution approval, audit, idempotency | change pipeline, `ChangeActionCard`, audit routes | `run_process` branch, `execution_result` column |
| Failure diagnosis | log tools' service calls, `parse_error_locations`, TI parser | Composite tool |
| Validation without save | `process_service.compile_process_dryrun`, `ti_analysis`, function reference | Tool wrapper |
| Review findings | the same three analysers | Dangerous-operation list, complexity metrics, one finding shape |
| Element and cell reads | TM1py `cells.get_values`, `elements.get_elements_filtered_by_wildcard`, MDX cell properties | Service wrappers |
| Evidence labelling | `ai_tool_executions`, stream events | Tool metadata + prompt rule + timeline |
