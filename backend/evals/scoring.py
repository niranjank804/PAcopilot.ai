"""Turn check results into a number that means something.

A raw pass rate treats an invented TI function and a missing comment as the
same event. Weighting by severity gives a score that moves when quality
moves: one critical failure outweighs any number of low ones, so a run
cannot be rescued by passing a lot of cheap checks.
"""

from dataclasses import dataclass, field

from evals.case import SEVERITY_WEIGHTS, EvalCase
from evals.checks import CheckResult


@dataclass
class CaseOutcome:
    case: EvalCase
    version: str | None
    results: list[CheckResult]
    failures_by_severity: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def worst_severity(self) -> str | None:
        for level in SEVERITY_WEIGHTS:
            if self.failures_by_severity.get(level):
                return level

        return None

    @property
    def penalty(self) -> int:
        return sum(
            SEVERITY_WEIGHTS[level] * len(names)
            for level, names in self.failures_by_severity.items()
        )


def outcome_for(
    case: EvalCase,
    results: list[CheckResult],
    version: str | None = None,
) -> CaseOutcome:
    failures: dict[str, list[str]] = {}

    for result in results:
        if result.passed:
            continue

        level = case.severity_of(result.name)
        failures.setdefault(level, []).append(result.name)

    return outcome(case, version, results, failures)


def outcome(case, version, results, failures) -> CaseOutcome:
    return CaseOutcome(
        case=case,
        version=version,
        results=results,
        failures_by_severity=failures,
    )


def score(outcomes: list[CaseOutcome]) -> dict:
    """Aggregate a run.

    `quality` is deliberately not a pass rate. It is the share of the
    maximum possible penalty that was avoided, so it degrades sharply on a
    critical failure and barely moves on a low one.
    """

    if not outcomes:
        return {
            "cases": 0,
            "passed": 0,
            "pass_rate": 0.0,
            "quality": 0.0,
            "failures_by_severity": {},
        }

    passed = sum(1 for item in outcomes if item.passed)

    by_severity: dict[str, int] = {}

    for item in outcomes:
        for level, names in item.failures_by_severity.items():
            by_severity[level] = by_severity.get(level, 0) + len(names)

    total_penalty = sum(item.penalty for item in outcomes)

    # One critical failure per case is the reference "as bad as it
    # realistically gets" — a case can accumulate more, which correctly
    # drives quality to zero.
    worst_case_penalty = len(outcomes) * SEVERITY_WEIGHTS["critical"]
    quality = max(0.0, 1 - (total_penalty / worst_case_penalty))

    return {
        "cases": len(outcomes),
        "passed": passed,
        "pass_rate": round(passed / len(outcomes), 4),
        "quality": round(quality, 4),
        "failures_by_severity": by_severity,
    }
