# PA-Copilot vs the Claude + TM1 benchmark — scorecard

Date: 2026-10-05. Repository state: `main` after phase 12 (monitoring) and
cell write-back.

**The benchmark** is the Claude + IBM Planning Analytics read-write setup
described in the PA-Copilot Enterprise brief: live TM1 Dev access over MCP,
about 114 named actions, read-only and read-write modes, compile, baseline
before overwrite, explicit confirmation, save, run, write, delete, rollback,
logging and Dev-only governance. It was **not run or tested here**; its
column records what the brief says it does.

**PA-Copilot's column** records what the code does, with the test or file
that shows it. "Verified" below means verified by automated tests against a
faked TM1 server, unless it says live. Against a real server, only
connecting, listing cubes and answering questions through the gateway were
confirmed (by the owner, 2026-09-28); compile, save, run and rollback
against a real Dev server are **not verified**.

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
| Golden workflows (12) | 10 automated end to end with evidence, 2 partial (explain calculation is unit-tested, incident analysis has no dedicated mode) |
| Live TM1 verification | Read paths confirmed by the owner; write paths **not verified** live |

So: by automated evidence PA-Copilot is **≥ the benchmark on every
benchmark capability** and ahead on the enterprise platform capabilities.
That is not yet a live result: the write paths, cell writes included, have
not been run against a real TM1 server.

## Scorecard

| Category | Capability | Claude benchmark (as described) | PA-Copilot | Evidence | Status | Advantage |
|---|---|---|---|---|---|---|
| TM1 access | Connect to TM1 / PAaaS | Live Dev access over MCP | Native, v12 SaaS and PA Cloud auth; on-premises through an outbound gateway; credentials encrypted at rest; connections private to their creator unless shared | `tests/unit/tm1/test_service.py`, `test_pa_cloud_connection.py`, `tests/integration/tm1/test_connection_isolation.py`; live read confirmed 2026-09-28 | Verified (read live) | PA-Copilot |
| TM1 access | Write cell values | "write" listed | A governed change (`write_cells`, `propose_cell_write`): leaf, non-rule cells of the right type only, up to 200; current values shown in the draft, saved and re-checked for drift when applying; the write is verified and undone if the server does not hold it; rollback writes the saved values back and refuses over later writes; never promoted; PROD two-person, AI read-only on PROD | `tests/integration/tm1/test_cell_writes.py` | Verified (not live) | PA-Copilot (approval, drift, verify, rollback) |
| Model discovery | Cubes, dimensions, hierarchies, elements, attributes, subsets, views, chores | Yes | 18 discovery tools, plus a persistent metadata graph with history and freshness | `tests/unit/ai/test_structure_tools.py`, `test_metadata_tools.py`, `tests/unit/tm1/test_extractor.py`, `test_metadata_history.py` | Verified | PA-Copilot (persistent graph) |
| Process engineering | Inspect, search, call tree, references | Yes | `get_process`, `search_process_code`, `get_process_call_tree`, `analyze_process_references` | `tests/unit/ai/test_process_tools.py`, `test_engineering_tools.py` | Verified | = |
| TI development | Generate and modify TI, server-side compile, review | Generation, modification, compile | Draft create/update/copy; compile on the server without saving (`validate_process_code`); TI review with dangerous-operation list; organization coding standards learned from exported processes | `tests/unit/ai/test_change_tools.py`, `test_engineering_tools.py`, `tests/unit/tm1/test_ti_review.py`; golden step 04 | Verified | PA-Copilot (standards, review) |
| Diagnostics | Logs, failure diagnosis | Logs, inspection | `diagnose_process_failure` maps the error log to the code line, marks evidence verified / inferred / unknown; message and transaction logs; who changed what recently | `tests/unit/tm1/test_failure_diagnosis.py`, `tests/unit/ai/test_log_tools.py`; golden step 03 | Verified (incident mode partial — see golden 12) | PA-Copilot |
| Dependency analysis | What depends on what; impact of a change | Dependency / impact analysis | Persistent graph; severity-ranked impact (critical/high/medium/low) on every draft; acknowledgement required for high impact | `tests/unit/tm1/test_impact_analysis.py`, `test_dependency_analyzer.py`; golden step 09 | Verified | PA-Copilot |
| Execution | Run a process | Run with confirmation | Run only as an approved change, parameters checked against the process, never retried, result and error log kept | `tests/unit/tm1/test_change_runs_and_guards.py`; golden step 07 | Verified (not live) | = |
| Deployment | Save to the server; promote | Save after confirmation, Dev only | Draft → impact → validation → approval → snapshot → apply → server verify; promotion DEV → QA → PROD with a deployment package (manifest, diff, impact, evidence, rollback plan) | `tests/unit/tm1/test_change_service.py`, `tests/integration/tm1/test_promotion.py`; golden steps 05, 06, 14 | Verified (not live) | PA-Copilot |
| Rollback | Restore the previous version | Baseline before overwrite, rollback | Snapshot on apply; rollback refuses if someone edited the object since; drift check refuses an apply over a changed server | `test_change_runs_and_guards.py`, `test_change_service.py`; golden step 15 | Verified (not live) | PA-Copilot (drift guards) |
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
| 12 | Production incident analysis | — | Pieces exist (recent model changes, change history, diagnosis, alerts, work items) but there is **no incident mode** that runs them as one timeline | **Partial** |

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
| Workflow completion | 10 / 12 golden workflows automated end to end; 2 partial |
| Safety | Every write is a draft; no tool calls TM1's mutating APIs (enforced by `test_tool_classification.py`); PROD two-person and AI read-only enforced |
| Accuracy | **Not measured.** No evaluation of answer quality against a real model has been run |
| Latency | **Not measured** against a real server. The product records it per request (p95 on the AI Cost panel) |
| Cost | **Not measured** in a benchmark run. The product records it per request |
| Deployment reliability | **Not measured live.** Automated: snapshot, drift refusal, rollback guards |
| Head-to-head with the benchmark | **Not run.** The benchmark setup was not available here |

## What would close the gaps

1. **Incident mode**: one command that identifies the environment and cube,
   lists recent changes and runs, compares snapshots, diagnoses, proposes a
   mitigation as a draft, and keeps the incident timeline (a work item can
   hold it).
2. **Live validation**: run `backend/tests/live/` against a real Dev server
   (see `backend/docs/live_validation/`), then the golden workflow against it.
3. **Power BI**, once there is a Microsoft Entra app registration.
4. **Accuracy evaluation**: a fixed question set scored against a real model.
