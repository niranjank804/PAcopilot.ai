# Live TM1 verification — inventory, evidence and status

Updated 2026-10-06. This page separates what is implemented from what has
been shown, and how. It does not claim production readiness, complete
security, universal TM1 compatibility, or guaranteed rollback.

## How evidence is classified

Every result is one of: PASS, FAIL, ERROR, SKIPPED, BLOCKED, UNSUPPORTED,
UNKNOWN. Four layers are kept apart, plus the transport:

| Layer | What it shows | What it does not |
|---|---|---|
| A. Direct TM1 API | TM1 behaves as the code assumes | anything about PA-Copilot's checks |
| B. Service / tool path | PA-Copilot's code against TM1 | API permissions, approval identity |
| C. Governed workflow | the HTTP API, two users, approval, audit, rollback | AI behaviour |
| D. AI behaviour | answers and tool choices of the real model | governance (never overrides a security failure) |

Transport: DIRECT (this machine to TM1) or GATEWAY (through the outbound
gateway). Only DIRECT has been exercised live.

## Capability inventory

| Capability | Implementation | Evidence (layer, how) | Changed since that evidence | Remaining gap |
|---|---|---|---|---|
| Private connections / isolation | `tm1/service.py` `may_access`, `get_connection` | C, faked TM1: `test_connection_isolation.py`, `test_denials_never_reach_tm1.py` (no decryption, no TM1 call on any denial) | denial suite added 2026-10-06 | live two-account check on production: not run |
| DEV/QA/PROD rights, PROD two-person | `tm1/governance.py` | C, faked TM1: `test_environments.py`, denial suite | — | — |
| Draft → approve → apply → verify → rollback (rules, processes) | `tm1/deployment/change_service.py` | B live (TM1 11.0.1, 2026-10-05, see provenance); C faked; C live harness written (`tests/live/test_governed_writes.py`), **not yet run** | outcome-unknown handling added 2026-10-06 | governed live run |
| Cell write-back | `change_service` `write_cells`, `cell_service.write_cells` | B live (2026-10-05); C faked: `test_cell_writes.py`; C live harness written, not yet run | cell writes made single-attempt 2026-10-06 | governed live run |
| Process runs and failures | `process_service.execute_process` (+ `tm1/compat.py` fallback) | B live (2026-10-05) | result now records the API used | governed live run |
| Compile without save | `validate_process_code` tool | faked TM1; live harness asserts no save is sent and the stored definition is unchanged, not yet run | — | governed live run |
| Ambiguous write outcomes | `TM1OutcomeUnknownError`; change status `unknown` | B, faked: `test_change_runs_and_guards.py` | added 2026-10-06 | cannot be safely provoked live |
| TM1 11.0 compatibility | `tm1/compat.py` | B live on 11.0.1 | — | 11.8, v12 / PAaaS: not tested |
| AI answer accuracy | `tests/live/test_answer_accuracy.py` | D live, 7 runs (2026-10-05/06), up to 17/18 | — | one sample model; not re-run (paid; needs LIVE_AI=1) |

## Historical evidence and its provenance

- `docs/evidence/live/live-run-2026-10-05_2028.txt` — 25/25 passed on TM1
  11.0.1 (Planning Sample), DIRECT. **Provenance:** the assistant obtained
  access by trying IBM's well-known sample default login, which the
  operator's rules now forbid; writes went through the change service
  (layer B), not the HTTP API with a separate approver; and write tests
  were gated by a typed server name only, not an operator inventory. It
  remains valid evidence of TM1 11.0.1 compatibility at layer B, and is
  kept unchanged. It is not evidence of the governed workflow.
- `docs/evidence/accuracy/run1`–`run7` — layer D, paid calls on the owner's
  key. Two answers were re-scored after check defects; the reports say so.
- `docs/evidence/golden/final_product_workflow.json` — layers B and C
  against a faked TM1.

## The current harness (2026-10-06)

`backend/scripts/run_live_validation.ps1` — read, write and paid AI are
separate opt-ins. Writes need all of: an inventory of approved DEV/test
servers the operator maintains (`%USERPROFILE%\.pa-copilot\live-targets.json`,
never written by a run), the server's name typed exactly and matching what
it reports, and a confirmed scope. Credentials are read masked, kept in the
process environment only, and stored (encrypted with a throwaway key, in the
local test database, rolled back with each test) only with explicit consent.

Fixtures are named `zzPACopilotLive_<run>_<kind>`, checked absent before
creation (a name that exists is refused, not adopted), recorded in
`manifest.json`, and cleaned up in dependency order with absence verified;
anything that could not be cleaned is listed there. Limits: 12 objects, 15
minutes, 60 s per process run, 30 s per request. Results go to
`results.json` from allowlisted fields only; raw test output is not saved.

What it cannot do: provoke an ambiguous outcome on a real server safely,
exercise the GATEWAY transport, or prove anything about production.
