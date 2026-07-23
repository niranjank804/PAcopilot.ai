# TM1 Compatibility Report

Copy this file (e.g. `reports/2026-07-21-<model-name>.md`) and fill it in after a live validation run. Treat the first run as a structured qualification exercise, not just "did pytest pass" — the goal is a factual basis for prioritizing whatever comes after Release 2, not a guess.

## Environment

- **Date**:
- **TM1 server version**:
- **Planning Analytics version**:
- **TM1py version**: (`pip show TM1py`)
- **Operating system**: (of the machine running the validation harness)
- **Deployment**: (on-prem / cloud / PA Engine v12 / other)
- **Auth mode used**: (Native / CAM / IBMid — note if CAM or IBMid, see the known gap in README.md)
- **Model name**:
- **Model size**: cubes = \_\_\_, dimensions = \_\_\_, processes = \_\_\_, chores = \_\_\_

## Summary

| Environment | Result |
|---|---|
| PA Version | |
| TM1 Server Version | |
| TM1py Version | |
| Authentication | |
| Metadata Extraction | Pass / Fail |
| Dependency Graph | Pass / Fail |
| AI Tools | Pass / Fail |
| Monitoring | Pass / Fail |
| Security API | Pass / Fail |
| Performance | (see numbers below) |
| Issues Found | (count — detail in `DEFECT_LOG_TEMPLATE.md`) |

## Results by area

| Area | Pass/Fail | Notes |
|---|---|---|
| Authentication | | |
| Metadata extraction | | |
| Rule parsing | | |
| TI parsing | | |
| Dependency engine | | |
| Error handling | | |
| Circuit breaker | | |
| Monitoring | | |
| AI personas | | |

## Performance numbers (from `tests/performance/benchmark_*.py`)

| Metric | Value |
|---|---|
| `list_cubes` time | |
| `get_cube` avg time (per cube) | |
| `list_dimensions` time | |
| `get_dimension` avg time (per dimension) | |
| Peak memory (metadata benchmark) | |
| `extract_metadata` time | |
| Objects created | |
| Relationships created | |
| `find_dependents` time (sample object) | |
| `find_dependencies` time (sample object) | |
| AI tool-call round-trip latency | |
| AI tokens (in/out) | |
| AI estimated cost | |

## Datasource types observed (from `test_datasource_types_seen_across_real_processes`)

-

## Findings requiring a decision

These three categories are what should actually drive what comes after Release 2 — capture them even if empty:

- **Parser failures** (Rules/TI — from `test_rules.py` and the reference-parser heuristic): none observed / see defect(s) # \_\_\_
- **TM1py API mismatches** (return shapes, exceptions, or kwargs that didn't match what the service layer assumed): none observed / see defect(s) # \_\_\_
- **Permission-related discrepancies** (TM1-side auth/permission errors that didn't map cleanly to `TM1AuthenticationError`/`TM1NotFoundError`): none observed / see defect(s) # \_\_\_

## Overall assessment

- [ ] Safe to proceed to Release 3 (TM1 Write Platform) planning
- [ ] Parser edge cases dominate — prioritize metadata extraction/parsing fixes first
- [ ] Authentication issues dominate — prioritize the auth abstraction (`TM1ConnectionFactory`) next
- [ ] Performance is the bottleneck — prioritize extraction/traversal optimization next
- [ ] Needs a larger/different model tested before deciding
