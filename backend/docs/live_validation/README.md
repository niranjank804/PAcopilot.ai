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

Every live test and benchmark creates its own throwaway `Organization`/`User`/`TM1Connection` row (via the same `db_session` savepoint-rollback fixture — or, for the standalone benchmark scripts, an explicit cleanup at the end) — nothing is left behind in your database, and nothing is written to the TM1 server itself; every operation exercised is read-only.

## Known gap: CAM / IBMid auth cannot be tested yet

`src/tm1/client/connection_manager.py::_connect()` only ever passes `address/port/ssl/user/password` to `TM1py`'s `TM1Service`. TM1py itself supports `namespace` (CAM), `api_key`/`iam_url` (IBMid / PA Engine v12), and several other auth modes — none of them are wired through `TM1Connection`, the create-connection API, or the connection manager today. If your validation server uses CAM or IBMid, only the plain server-connectivity smoke test will work meaningfully; extending the connection layer to support those modes is a small, separate, scoped change — flag it if you hit this, rather than treating a CAM auth failure here as a defect in the read platform.
