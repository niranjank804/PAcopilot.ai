# Live Validation Checklist

Check each row off after a real run against your TM1 server. "Covered by" points to the automated test/benchmark; "Manual" rows have no automated coverage yet and need eyes-on review of the printed output or the compatibility report.

| Area | Validation | Covered by | Status |
|---|---|---|---|
| **Authentication** | Native (user/password) over SSL | `tests/live/test_connection.py` | ☐ |
| | Wrong-password rejection | `tests/live/test_connection.py` | ☐ |
| | CAM | — **not testable yet**, see README "Known gap" | ☐ N/A until connection layer supports it |
| | IBMid / PA Engine v12 | — **not testable yet**, see README "Known gap" | ☐ N/A until connection layer supports it |
| | Session renewal / long-lived sessions | Manual — run the live suite twice in a row, minutes apart, confirm the second run's `test_connection` still succeeds | ☐ |
| **Metadata** | Cubes | `tests/live/test_metadata.py` | ☐ |
| | Dimensions | `tests/live/test_metadata.py` | ☐ |
| | Hierarchies | `tests/live/test_metadata.py::test_get_dimension_returns_real_shape` (hierarchy_names) | ☐ |
| | Attributes | — not yet part of the metadata graph (deferred, see project memory: "Attributes... better suited to a plain `get_dimension_attributes` tool later") | ☐ N/A this round |
| | Chores | `tests/live/test_processes.py` pattern extends to chores — add a `test_chores` case if your model has chores and this matters for your validation | ☐ |
| | Processes | `tests/live/test_processes.py` | ☐ |
| | Rules | `tests/live/test_rules.py` | ☐ |
| **Rule Parsing** | Large rule files | `tests/live/test_rules.py` (prints rule length per cube — review for anything surprisingly large or slow) | ☐ |
| | Comments, feeders, unusual formatting | `tests/live/test_rules.py::test_reference_parser_against_a_known_real_rule_cube` — set `TM1_TEST_CUBE_WITH_RULES` | ☐ |
| **TI Parsing** | All datasource types (Cube, ASCII, ODBC, View, ...) | `tests/live/test_processes.py::test_datasource_types_seen_across_real_processes` — prints every distinct type seen; confirm each is handled by `src/tm1/services/process_service.py` and `reference_parser.extract_ti_cube_writes` | ☐ |
| **Dependency Engine** | Lineage against actual models | `tests/live/test_dependencies.py` | ☐ |
| **Performance** | Metadata extraction time | `tests/performance/benchmark_metadata.py`, `benchmark_graph.py` | ☐ |
| | Memory usage | `tests/performance/benchmark_metadata.py` (tracemalloc peak) | ☐ |
| **Error Handling** | Invalid objects (404s) | Manual — call `get_cube`/`get_process`/etc. with a made-up name and confirm a clean `TM1NotFoundException`, not a crash | ☐ |
| | Permission failures | Manual — use TM1 credentials for a low-privilege user against an object they can't read | ☐ |
| | Other TM1py exceptions | Manual — review console output for any unhandled exception type during the live run | ☐ |
| **Circuit Breaker** | Connection failures | `tests/live/test_connection.py::test_test_connection_fails_with_wrong_password` (auth failure path); for network failures, point `TM1_ADDRESS` at an unreachable host temporarily | ☐ |
| | Timeouts | Manual — lower `TM1_REQUEST_TIMEOUT_SECONDS` and hit a slow operation | ☐ |
| | Server restarts | Manual — restart the TM1 server mid-run and confirm the circuit breaker opens, then recovers after the cooldown | ☐ |
| **Monitoring** | Usage metrics | `tests/live/test_monitoring.py::test_usage_summary_endpoint_does_not_error_against_real_data` | ☐ |
| | Breaker state | `tests/live/test_monitoring.py::test_circuit_breaker_reads_closed_after_real_success` | ☐ |
| | Latency | `tests/performance/benchmark_ai.py`, `benchmark_metadata.py` | ☐ |
| **AI Personas** | End-to-end tool execution with real metadata | `tests/live/test_ai_tools.py` (developer persona; extend with the same pattern for performance/administrator/architect/documentation if you want deeper coverage) | ☐ |

After completing a pass, fill in `COMPATIBILITY_REPORT_TEMPLATE.md` and log anything unexpected in `DEFECT_LOG_TEMPLATE.md`.
