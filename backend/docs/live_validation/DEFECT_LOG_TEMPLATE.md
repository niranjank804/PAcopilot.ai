# Defect Log — Mocked Assumption vs. Real TM1 Behavior

Copy this file per validation run. One row per divergence found. The point of this log isn't just "what broke" — it's specifically "what did the mocks let us assume that wasn't true," since that's the risk this whole validation round exists to retire.

| # | Area | Expected (per mocks / code assumption) | Actual (real TM1 behavior) | Severity | Suspected cause | Linked test |
|---|---|---|---|---|---|---|
| 1 | | | | Critical / High / Medium / Low | | |
| 2 | | | | | | |

**Severity guide**:
- **Critical** — crashes, data corruption risk, or a security-relevant behavior gap (e.g. the security-groups exclusion not holding).
- **High** — a whole feature area doesn't work against this model (e.g. a datasource type the extractor doesn't handle).
- **Medium** — a specific object or edge case fails, workable-around for now.
- **Low** — cosmetic, or a performance number worse than hoped but not blocking.

Every row here is a candidate follow-up round, scoped and planned the same way every other round in this project has been — not silently patched inline.
