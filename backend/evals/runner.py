"""Run the deterministic checks for a case against an answer.

Deliberately separated from *producing* the answer. Generating answers costs
provider money and needs a live key; checking them costs nothing. Keeping
the two apart means the whole check layer is unit-testable, and a golden
answer can be re-verified in CI on every commit for free.
"""

from evals.case import EvalCase
from evals.checks import (
    CheckResult,
    check_absent,
    check_functions_are_real,
    check_present,
    check_qualified,
)
from evals.scoring import CaseOutcome, outcome_for


def run_checks(
    case: EvalCase,
    answer: str,
    version: str | None = None,
) -> list[CheckResult]:
    """Every deterministic check the case declares, in a stable order."""

    results: list[CheckResult] = []
    checks = case.checks

    if "functions_are_real" in checks:
        config = checks["functions_are_real"] or {}
        results.append(
            check_functions_are_real(
                answer,
                context=config.get("context", "TI"),
                version=version,
            )
        )

    if checks.get("present"):
        results.append(check_present(answer, checks["present"]))

    if checks.get("absent"):
        results.append(check_absent(answer, checks["absent"]))

    for rule in checks.get("qualified") or []:
        results.append(
            check_qualified(
                answer,
                rule["term"],
                rule.get("qualifiers") or [],
                window=rule.get("window", 400),
            )
        )

    return results


def evaluate(case: EvalCase, answer: str) -> list[CaseOutcome]:
    """One outcome per supported TM1 version.

    A function valid on v11 and withdrawn in v12 makes an answer correct for
    one server and wrong for the other, so the versions are scored
    separately rather than collapsed into a single verdict.
    """

    versions = case.supported_versions or [None]

    return [
        outcome_for(case, run_checks(case, answer, version), version)
        for version in versions
    ]
