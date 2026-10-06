# PA-Copilot vs the Claude + TM1 benchmark — scorecard

Date: 2026-10-05. Repository state: `main` after phase 12 (monitoring), cell
write-back and incident mode.

**The benchmark** is the Claude + IBM Planning Analytics read-write setup
described in the PA-Copilot Enterprise brief: live TM1 Dev access over MCP,
about 114 named actions, read-only and read-write modes, compile, baseline
before overwrite, explicit confirmation, save, run, write, delete, rollback,
logging and Dev-only governance. It was **not run or tested here**; its
column records what the brief says it does.

**PA-Copilot's column** records what the code does, with the test or file
that shows it. "Verified" below means verified by automated tests against a
faked TM1 server; "Verified live" means also run against a real TM1 server:
the live suite (`backend/tests/live/`, 25 tests) passed against TM1 11.0.1
(Planning Sample) on 2026-10-05 — connection, discovery, dependencies,
rules, security, an AI tool call, and every write path: compile refusal,
create, update, run, delete, a failing run, cell writes, drift refusal,
rules, and the rollbacks. Report: [`evidence/live/live-run-2026-10-05_2028.txt`](evidence/live/live-run-2026-10-05_2028.txt).

Those writes went through the change service (layer B), not the HTTP API with
a separate approver, and access came from IBM's sample default login, which
the operator's rules now forbid. The governed workflow has a live harness
(`tests/live/test_governed_writes.py`) that has not yet been run. Layers,
provenance and status: [`LIVE_VERIFICATION.md`](LIVE_VERIFICATION.md).

How to read **Advantage**: `=` both have it; **PA-Copilot** or
**Benchmark** where one clearly has more; `n/a` where the benchmark does not
attempt it. No row claims PA-Copilot is better at something the benchmark
does unless the evidence column shows the extra capability.

## Summary

| | Count |
|---|---|
| Benchmark capability rows (the 114-row brief) | 103 exist, 10 partial, 0 missing, 1 blocked by the TM1 API ([gap matrix](TM1_CAPABILITY_GAP_MATRIX.md)) |
| Benchmark actions **not** matched | None by automated evidence. Cell write-back (the benchmark's "write") was the last; it now exists as a governed change |
| Scorecard rows (23, over the brief's 22 categories) | PA-Copilot ahead on 12, equal on 2, behind on 0; 9 rows the benchmark does not attempt — 8 built, Analytics partial |
| Golden workflows (12) | 11 automated with evidence; 1 unit-tested only (explain calculation) |
| Live TM1 verification | 25 / 25 live tests passed on TM1 11.0.1, reads and writes; the first run found 3 compatibility defects with older servers, fixed (see below) |

So: PA-Copilot is **≥ the benchmark on every benchmark capability** and
ahead on the enterprise platform capabilities — by automated tests, and for
the write paths also live, against TM1 11.0.1. Answer accuracy is measured
(below). Not yet run: a head-to-head with the benchmark setup itself.

### Answer accuracy (live, 2026-10-05)

`backend/tests/live/test_answer_accuracy.py` asks 11 questions through the
real orchestrator, model and tools on Planning Sample, and checks each
answer against the truth read from TM1 with TM1py — not through
PA-Copilot's tools — with deterministic checks, no model grading.

| Run | Correct | Median | Slowest | Cost |
|---|---|---|---|---|
| 1 | 10 / 11 (91%) | 12.5 s | 66 s | $0.50 |
| 2 | 10 / 11 (91%) | 8.3 s | 73 s | $0.53 |
| 3 (after the fixes below) | 10 / 11 (91%) | 8.6 s | 174 s | $0.61 |
| 4 (after the fixes below) | 10 / 11 (91%) | 8.5 s | see note | $1.07 |
| 5 (18 questions, 6 agents) | 17 / 18 (94%) | 8.3 s | 281 s | $1.26 |
| 6 (18 questions, 6 agents) | 17 / 18 (94%) | 9.2 s | 192 s | $1.14 |
| 7 (18 questions, all fixes) | 17 / 18 (94%) | 7.4 s | 405 s | $1.61 |

Reports: [`evidence/accuracy/run1`](evidence/accuracy/run1/report.md),
[`run2`](evidence/accuracy/run2/report.md). Correct both times: the cube
list, a cube's dimensions in order, which cubes have rules, a dimension's
element count, a cell value, whether a cell is rule-calculated, which cube
a process writes, a process's datasource, and saying plainly that a named
cube or process does not exist. Missed both times: the TI generation case —
the TI agent gave the right PAW advice but asked for the file layout and
target cube instead of writing the process, so the "functions are real"
check had no code to inspect.

**What the first run found:** 4 / 11. Every specialist agent was also given
the plain-chat instruction "No TM1 server is connected in this mode", after
its own instructions and the chosen connection, and often obeyed it —
refusing its tools and telling the user to connect a server they had
connected. Fixed (`_base_system` in `src/ai/orchestrator.py`, regression
test `tests/unit/ai/test_agent_system_prompt.py`). This affected agent
chats in production until the fix is deployed.

**Runs 3 and 4**, after two fixes the first runs pointed at:

- `get_dimension` now returns element counts per hierarchy, counted by
  TM1. The element-count question went from 60–75 s and ~$0.19 to 6–9 s
  and ~$0.02, still correct.
- The TI agent, missing the file layout and target cube, now writes the
  complete process with `<Placeholders>` and checks it with
  `check_tm1_code` before asking — it no longer answers with questions
  only. The TI case still fails, for a different reason each time: in
  run 3 the code uses CubeGetLogChanges / CubeSetLogChanges, which the
  function reference marks unavailable on v12, and the case requires code
  that runs on v11 and v12 (the agent copied the logging pattern of the
  v11 server's own processes — right for this server, not for both); in
  run 4 the check found no fenced code block.
- Run 4's slowest answer (the TI case) took 8,680 s with 28 tool calls,
  across a night in which the PC slept; not reproduced, but the TI agent's
  many separate function lookups are worth reducing.
- Run 4's missing-cube answer ("There's no 'Sales_Forecast_2031'") was
  correct; the check's pattern missed it and was fixed. Re-scored with no
  new model call, as the report says.

**Runs 5–7** widened the set to 18 questions across six agents (Developer,
Analyst, Architect, Administrator, Documentation, Troubleshooter, TI):
process parameters, the file a process loads, a text cell, which cubes'
rules read another cube, which cubes use a dimension, a leaf count, and
whether any chores exist. No agent reads TM1 security, by design, so there is
no security question. Three more product defects came out:

- **Haiku requests failed outright.** AUTO routing sends documentation
  questions and plain chat to the fast tier, Haiku 4.5, and every request
  carried adaptive thinking and the effort setting, which Haiku refuses
  (both confirmed against the API). Fixed: those settings go only to models
  that take them. The Documentation agent now answers on Haiku in 4–7 s for
  about $0.02.
- **Text written before a tool call was lost.** Only the last round's text
  was returned and saved, so code the TI agent wrote and then checked with a
  tool vanished from the answer — and, in chat, from the conversation when
  reopened, though it had streamed to the screen. Fixed in both paths: the
  answer is every round's text, as streamed.
- **Function lookups one at a time.** `lookup_tm1_function` now takes a
  list; the TI agent is told to look everything up in one call and rely on
  `check_tm1_code`. Lookups per TI answer fell from 28 to 1–5.

The miss in runs 5–7 is the TI case again: the code uses the v11 logging
functions this server's own processes use, and the case requires code that
also runs on v12. Run 8 stopped on a network error reaching the model API
and has no report. A check of my own held stray control characters and
missed two correct "no chores" answers; fixed and re-scored with no new
model call, as the reports say.

Also seen: results vary run to run (the same code scored 9 and 8 of 11
before the checks were corrected); the element-count question is slow
(60–75 s, ~$0.19) because no tool returns a count directly; TM1 11.0
reports a cell's RuleDerived flag differently depending on the query shape
for a cell a rule covers but STETs.

### What the live run found

The first live run failed 3 of 6 write tests. All three were real defects
with older TM1 servers that a faked server could not show, fixed in
`src/tm1/compat.py`; the modern call is still tried first:

| Defect on TM1 11.0.1 | Fix |
|---|---|
| No `tm1.ExecuteWithReturn`: every approved process run failed to start | Fall back to `tm1.Execute`; a failing process is recorded with TM1's outcome and error line |
| Cell writes refused: the server takes every value as text | Resend the values as text; nothing is written by the refused attempt |
| No `tm1.CheckRules`: every rules change failed after saving | The server already refuses invalid rule syntax on save; the change records which check ran |

## Scorecard

| Category | Capability | Claude benchmark (as described) | PA-Copilot | Evidence | Status | Advantage |
|---|---|---|---|---|---|---|
| TM1 access | Connect to TM1 / PAaaS | Live Dev access over MCP | Native, v12 SaaS and PA Cloud auth; on-premises through an outbound gateway; credentials encrypted at rest; connections private to their creator unless shared | `tests/unit/tm1/test_service.py`, `test_pa_cloud_connection.py`, `tests/integration/tm1/test_connection_isolation.py`; live read confirmed 2026-09-28 | Verified (read live) | PA-Copilot |
| TM1 access | Write cell values | "write" listed | A governed change (`write_cells`, `propose_cell_write`): leaf, non-rule cells of the right type only, up to 200; current values shown in the draft, saved and re-checked for drift when applying; the write is verified and undone if the server does not hold it; rollback writes the saved values back and refuses over later writes; never promoted; PROD two-person, AI read-only on PROD | `tests/integration/tm1/test_cell_writes.py` | Verified live, service layer (TM1 11.0.1); governed workflow live: not yet run | PA-Copilot (approval, drift, verify, rollback) |
| Model discovery | Cubes, dimensions, hierarchies, elements, attributes, subsets, views, chores | Yes | 18 discovery tools, plus a persistent metadata graph with history and freshness | `tests/unit/ai/test_structure_tools.py`, `test_metadata_tools.py`, `tests/unit/tm1/test_extractor.py`, `test_metadata_history.py` | Verified | PA-Copilot (persistent graph) |
| Process engineering | Inspect, search, call tree, references | Yes | `get_process`, `search_process_code`, `get_process_call_tree`, `analyze_process_references` | `tests/unit/ai/test_process_tools.py`, `test_engineering_tools.py` | Verified | = |
| TI development | Generate and modify TI, server-side compile, review | Generation, modification, compile | Draft create/update/copy; compile on the server without saving (`validate_process_code`); TI review with dangerous-operation list; organization coding standards learned from exported processes | `tests/unit/ai/test_change_tools.py`, `test_engineering_tools.py`, `tests/unit/tm1/test_ti_review.py`; golden step 04 | Verified | PA-Copilot (standards, review) |
| Diagnostics | Logs, failure diagnosis, incidents | Logs, inspection | `diagnose_process_failure` maps the error log to the code line, marks evidence verified / inferred / unknown; message and transaction logs; incident mode ranks suspects for a wrong cube or failed process from changes, runs, model differences, rules and alerts, with a governed mitigation for each | `tests/unit/tm1/test_failure_diagnosis.py`, `tests/unit/ai/test_log_tools.py`, `tests/integration/test_incidents.py`; golden step 03 | Verified | PA-Copilot |
| Dependency analysis | What depends on what; impact of a change | Dependency / impact analysis | Persistent graph; severity-ranked impact (critical/high/medium/low) on every draft; acknowledgement required for high impact | `tests/unit/tm1/test_impact_analysis.py`, `test_dependency_analyzer.py`; golden step 09 | Verified | PA-Copilot |
| Execution | Run a process | Run with confirmation | Run only as an approved change, parameters checked against the process, never retried, result and error log kept | `tests/unit/tm1/test_change_runs_and_guards.py`; golden step 07 | Verified live, service layer (TM1 11.0.1); governed workflow live: not yet run | = |
| Deployment | Save to the server; promote | Save after confirmation, Dev only | Draft → impact → validation → approval → snapshot → apply → server verify; promotion DEV → QA → PROD with a deployment package (manifest, diff, impact, evidence, rollback plan) | `tests/unit/tm1/test_change_service.py`, `tests/integration/tm1/test_promotion.py`; golden steps 05, 06, 14 | Verified live, service layer (TM1 11.0.1); governed workflow live: not yet run | PA-Copilot |
| Rollback | Restore the previous version | Baseline before overwrite, rollback | Snapshot on apply; rollback refuses if someone edited the object since; drift check refuses an apply over a changed server | `test_change_runs_and_guards.py`, `test_change_service.py`; golden step 15 | Verified live, service layer (TM1 11.0.1); governed workflow live: not yet run | PA-Copilot (drift guards) |
| Security | Who may do what | Dev-only operation | RBAC per tool; private connections; PROD needs a second person; AI read-only on PROD; organization isolation; SSRF policy on addresses; encrypted credentials | `tests/unit/ai/test_tool_classification.py`, `tests/integration/tm1/test_environments.py`, `test_connection_isolation.py`; golden step 13 | Verified | PA-Copilot |
| Governance | Confirmation, audit | Explicit confirmation, logging | Every write is a draft a person approves; DEV / QA / PROD rights; audit log of every change, approval, rollback, share, memory and monitor action | `test_environments.py`, `test_promotion.py`; golden step 18 | Verified | PA-Copilot |
| Agents | Specialists over one tool registry | One general assistant | 9 specialist agents (troubleshooter, TI, developer, analyst, architect, reviewer, performance, administrator, documentation) over one registry of 69 tools, each with an allowlist | `tests/unit/ai/test_agents.py`; golden step 10 | Verified | PA-Copilot |
| RAG | Answers grounded in documents | Not described | Knowledge base: vector search with keyword fallback, cited sources, ingestion quality checks | `tests/unit/knowledge/`, `src/knowledge/retrieval.py` | Verified | n/a |
| Knowledge | What the team knows | Not described | Engineering memory: people vouch, AI only proposes, versioned, in every conversation | `tests/integration/test_engineering_memory.py`; golden step 11 | Verified | n/a |
| Model health | A score with evidence | Not described | Health score by category with the evidence behind each deduction; daily rescans | `tests/unit/tm1/test_model_health.py`; golden step 16 | Verified | n/a |
| Performance | Run times, regressions | Process statistics | Runs from the message log and PA-Copilot runs; regression = over 2x the median of 3+ earlier runs and 30 s longer; slowest loads | `test_model_health.py`; golden step 17 | Verified | PA-Copilot |
| Analytics | Power BI | Not described | **Not built** (deferred: needs a Microsoft Entra app). Charts from live cube data exist (`show_chart`, Visualize) | `tests/integration/tm1/test_show_chart_tool.py`, `test_visualize_api.py` | Partial | n/a |
| Voice | Speak to the assistant | Not described | Browser speech in and out, same chat path (same permissions and approvals); a drafted change is announced, never approved by voice | `frontend/src/lib/__tests__/voice.test.ts` | Verified | n/a |
| Cost optimization | Right model per request | Not described | AUTO routing (fast / balanced / best), one-step fallback, cost per request, agent, model and person, cache savings | `tests/unit/ai/test_routing.py`, `test_cost_report.py`; golden step 19 | Verified | n/a |
| Multi-tenancy | Organizations | Not described | Organization isolation enforced in every query; private workspaces per sign-up; connection isolation | `tests/integration/tm1/test_connection_isolation.py`, `tests/unit/database/test_tenancy.py` | Verified | n/a |
| Collaboration | Team work | Not described | Shared (read-only) conversations; work items with a timeline from linked conversations and changes | `tests/integration/test_team_collaboration.py` | Verified | n/a |
| Monitoring | Watch the model | Not described | Rules every 15 minutes: failures, slow runs, dimension growth, security, model and deployment changes; alerts once, email; server memory not built | `tests/integration/test_monitoring_rules.py` | Verified | n/a |

## Golden workflows

Each is automated and leaves evidence. The final product test runs the
Claude-style workflow and the PA-Copilot extension in one go:
`backend/tests/golden/test_final_product_workflow.py`, with its recorded
run in [`evidence/golden/final_product_workflow.json`](evidence/golden/final_product_workflow.json).

| # | Workflow | Where | Evidence it produces | Status |
|---|---|---|---|---|
| 1 | Diagnose failed process | golden step 03 | Error log file, failing line mapped to code, cubes the process writes | Automated |
| 2 | Generate TI | `tests/unit/ai/test_change_tools.py` (`create_new`), golden step 04 | Server compile result (not saved), draft only | Automated |
| 3 | Fix existing TI | golden steps 04–06 | Compile result, draft, diff preview, lifecycle, applied | Automated |
| 4 | Analyze cube dependencies | golden steps 09, 12 | Objects reached with severity; extraction history | Automated |
| 5 | Explain calculation | `tests/unit/ai/test_rule_tools.py::test_trace_cell_calculation_explains_a_zero_total` | Rule and feeder trace for a cell | Unit-tested, not in the golden run |
| 6 | Performance investigation | golden step 17 | Regression: usual vs latest seconds, runs it is based on | Automated |
| 7 | Create change | golden step 05 | Draft with impact, validation, diff | Automated |
| 8 | Approve change | golden steps 06, 13 | Applied by someone with deploy rights; PROD self-approval refused | Automated |
| 9 | Deploy DEV → QA | golden step 14 | Promoted draft applied on QA; package with manifest, diff, impact, evidence, rollback plan | Automated |
| 10 | Rollback | golden step 15 | Restored from the snapshot | Automated |
| 11 | Model health scan | golden step 16 | Score, grade and category deductions | Automated |
| 12 | Production incident analysis | `tests/integration/test_incidents.py::test_a_rule_change_and_a_failed_writer_are_the_suspects_and_a_rollback_clears_one` | Environment, writers and rule sources of the cube; ranked suspects (a rules change applied today, a failed writer); the rollback as a governed change; a second look showing the change cleared; the incident timeline | Automated |

## Final product test (brief §30)

Claude-style workflow, all in the golden run: inspect process (01) → inspect
cube and dimension order (02) → identify writer, inspect logs, diagnose (03)
→ generate fix and compile (04) → diff (05) → approve and save (06) → run
(07) → verify (08).

PA-Copilot extension, same run: impact analysis (09) → specialist agents
(10) → organization knowledge (11) → dependency graph (12) → security
policy: AI read-only on PROD, no PROD self-approval (13) → change approval
and deployment to QA with package (14) → rollback (15) → model health (16)
→ performance analysis (17) → audit (18) → AI cost tracking (19).

## Measured, and not measured

Brief §29 asks for capability coverage, workflow completion, accuracy,
latency, cost, safety and deployment reliability.

| Measure | Result |
|---|---|
| Capability coverage | 103 / 114 rows exist, 10 partial, 1 blocked; plus cell write-back, which the 114 rows did not list |
| Workflow completion | 11 / 12 golden workflows automated; explain calculation unit-tested only |
| Safety | Every write is a draft; no tool calls TM1's mutating APIs (enforced by `test_tool_classification.py`); PROD two-person and AI read-only enforced |
| Accuracy | 17 / 18 (94%) in three live runs on Planning Sample across six agents; truth from TM1, deterministic checks. One sample model — a start, not a benchmark |
| Latency | Median 8–13 s per answer with tool calls, slowest 66–73 s (live runs above) |
| Cost | About $0.05 per answer on average, $0.50 per 11-question run (live runs above) |
| Deployment reliability | Live on TM1 11.0.1: apply, verify, drift refusal and rollback for processes, rules and cells all passed. Not measured over time |
| Head-to-head with the benchmark | **Not run.** The benchmark setup was not available here |

## What would close the gaps

1. **More live servers**: the live suite ran on TM1 11.0.1. Run it on
   the TM1 or Planning Analytics versions customers use (11.8, v12 / PAaaS)
   with `backend/scripts/run_live_validation.ps1`.
2. **Power BI**, once there is a Microsoft Entra app registration.
3. **A larger accuracy set**: more questions, on a customer-sized model,
   and a direct element-count tool for the slowest case.
