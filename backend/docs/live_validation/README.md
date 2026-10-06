# Live TM1 Validation

Everything in this platform has been verified against **mocked** TM1py clients and a mocked Anthropic provider. This directory holds the harness for validating it against a **real** TM1 server — something that has to run in your environment, since credentials for a real server are never accepted by or sent through chat.

## What's here

- `tests/live/` — pytest tests that exercise the real application stack (connection manager, resilience, metadata extraction, dependency graph, security APIs, monitoring, AI tool-calling) against a real TM1 server. They **skip automatically** (not fail) if the required environment variables aren't set, so it's always safe to run the full suite here, on your own machine, or in CI.
- `tests/performance/benchmark_*.py` — standalone scripts (not pytest tests) that time and measure memory for metadata extraction, graph traversal, and one AI tool-call round trip.
- `CHECKLIST.md` — the validation scope, mapped to which test file covers each area.
- `COMPATIBILITY_REPORT_TEMPLATE.md` — fill in after a validation run against a specific TM1 model.
- `DEFECT_LOG_TEMPLATE.md` — record any divergence between what the mocks assumed and what the real server actually did.

## Required environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `TM1_ADDRESS` | Yes | — | TM1 REST API host |
| `TM1_USER` | Yes | — | Native TM1 user |
| `TM1_PASSWORD` | Yes | — | Native TM1 password |
| `TM1_PORT` | No | `8010` | |
| `TM1_SSL` | No | `true` | `true`/`false` |
| `TM1_NAMESPACE` | No | — | Accepted for forward-compat only — **not yet wired through the connection layer**. See "Known gap" below. |
| `TM1_TEST_CUBE_WITH_RULES` | No | — | Name of a real cube with non-trivial rules, to run the rule-reference-parser heuristic against real syntax (`tests/live/test_rules.py`) |
| `ANTHROPIC_API_KEY` | Only for `test_ai_tools.py` / `benchmark_ai.py` | — | Independent of the `TM1_*` vars — those two files skip on their own if this is missing, everything else still runs |

Only **Native auth (user/password) over HTTP/HTTPS** can actually be exercised today — see "Known gap" below before testing a CAM or IBMid-secured server.

## Running it

```bash
# from backend/, with the venv active and the env vars above set:
PYTHONPATH=. pytest tests/live -m live -v

# or, to also run the rest of the suite (the 211 mocked tests) in the same pass:
PYTHONPATH=. pytest -v

# benchmarks (not pytest — run directly):
PYTHONPATH=. python tests/performance/benchmark_metadata.py
PYTHONPATH=. python tests/performance/benchmark_graph.py
PYTHONPATH=. python tests/performance/benchmark_ai.py   # also needs ANTHROPIC_API_KEY
```

Every live test and benchmark creates its own throwaway `Organization`/`User`/`TM1Connection` row (via the same `db_session` savepoint-rollback fixture — or, for the standalone benchmark scripts, an explicit cleanup at the end) — nothing is left behind in your database. Read, write and paid-AI validation are separate opt-ins; choosing one never
enables another.

## Write validation (opt-in, DEV/test only)

`tests/live/test_governed_writes.py` runs the governed workflow through
PA-Copilot's own HTTP API, as two disposable users (an author who drafts and
an approver who applies): process create / update / delete with rollbacks,
a reviewed run and a safe failing run, compile-without-save (asserting no
save is sent and the stored definition is unchanged), cell writes with every
refusal rule, drift and rollback-over-newer refusal, and rules (invalid
syntax refused with the last valid rules kept, apply, calculate, roll back).
TM1 is touched directly only to create run-owned fixtures and to verify
results independently.

Writes happen only when all of these hold — otherwise the tests are BLOCKED
before anything is sent:

| Condition | How |
|---|---|
| Opt-in | `TM1_LIVE_WRITE=1` |
| The target is one you approved | listed in `%USERPROFILE%\.pa-copilot\live-targets.json` (or `LIVE_TARGETS_FILE`), which you maintain; a run never writes it |
| You named it | `TM1_LIVE_WRITE_SERVER` equals the name the server reports |
| You confirmed the scope | `LIVE_WRITE_SCOPE_CONFIRMED=1` |

Inventory format: `[{"address": "localhost", "port": 12354, "server_name": "Planning Sample", "purpose": "DEV sample"}]`.

Fixtures are named `zzPACopilotLive_<run>_<kind>`, refused if the name
already exists, and cleaned up with absence verified; see `manifest.json`.

## Credentials

The script reads the password masked and keeps it in its own process
environment for the run. Tests that create a connection store it the way
the product does — encrypted, here with a throwaway key, in the local test
database, rolled back with each test — and only with your consent
(`LIVE_CREDENTIAL_STORAGE_CONSENT=1`); otherwise they are BLOCKED.

## Paid AI

`tests/live/test_ai_tools.py` and `tests/live/test_answer_accuracy.py` call
the model and cost money. They run only with `LIVE_AI=1` (and, for the
accuracy run, `ACCURACY_EVAL=1`) — never because a key is present.

## The easy way, on Windows, from the repository root

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\run_live_validation.ps1
```

Evidence (allowlisted fields only; raw output is not saved) goes to
`docs/evidence/live/<run>/`: `run.json`, `manifest.json`, `results.json`.

## Known gap: CAM / IBMid auth cannot be tested yet

`src/tm1/client/connection_manager.py::_connect()` only ever passes `address/port/ssl/user/password` to `TM1py`'s `TM1Service`. TM1py itself supports `namespace` (CAM), `api_key`/`iam_url` (IBMid / PA Engine v12), and several other auth modes — none of them are wired through `TM1Connection`, the create-connection API, or the connection manager today. If your validation server uses CAM or IBMid, only the plain server-connectivity smoke test will work meaningfully; extending the connection layer to support those modes is a small, separate, scoped change — flag it if you hit this, rather than treating a CAM auth failure here as a defect in the read platform.
