"""Case loading, version-aware evaluation, and severity scoring."""

import pytest

from evals.case import SEVERITY_WEIGHTS, load_case, load_cases
from evals.checks import CheckResult
from evals.runner import evaluate
from evals.scoring import outcome_for, score


@pytest.fixture
def paw_case():
    cases = load_cases(domain="ti")
    return next(c for c in cases if c.name == "paw_fixed_width_load")


def test_cases_load_from_domain_folders(paw_case):
    assert paw_case.domain == "ti"
    assert paw_case.agent == "ti"
    assert "regression" in paw_case.tags


def test_a_case_declares_its_supported_versions(paw_case):
    assert paw_case.supported_versions == ["v11", "v12"]


def test_golden_answer_is_discovered_next_to_the_case(paw_case):
    golden = paw_case.golden()

    assert golden is not None
    assert "CharacterDelimited" in golden


def test_golden_answer_passes_on_every_supported_version(paw_case):
    outcomes = evaluate(paw_case, paw_case.golden())

    assert [o.version for o in outcomes] == ["v11", "v12"]
    assert all(o.passed for o in outcomes), [
        r for o in outcomes for r in o.results if not r.passed
    ]


def test_a_bad_answer_fails_on_every_version(paw_case):
    answer = "```tm1\nsA = SUBSTRING( v1, 1, 5 );\n```"

    outcomes = evaluate(paw_case, answer)

    assert all(not o.passed for o in outcomes)


def test_invented_function_is_scored_critical(paw_case):
    answer = "```tm1\nsA = SUBSTRING( v1, 1, 5 );\n```"

    outcome = evaluate(paw_case, answer)[0]

    assert outcome.worst_severity == "critical"


def test_severity_is_taken_from_the_case_not_the_default(paw_case):
    # The case promotes `qualified` from the default 'high' to 'critical'.
    assert paw_case.severity_of("qualified:PositionDelimited") == "critical"
    assert paw_case.severity_of("present") == "medium"


def test_an_unknown_severity_fails_at_load_time(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\nprompt: x\nseverity:\n  present: catastrophic\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected one of"):
        load_case(path)


def test_a_missing_prompt_fails_at_load_time(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt"):
        load_case(path)


# --------------------------------------------------------------------------
# Scoring.
# --------------------------------------------------------------------------


def _outcome(case, failures):
    results = [CheckResult(name, False) for name in failures]
    return outcome_for(case, results)


def test_quality_is_not_a_pass_rate(paw_case):
    one_critical = score([_outcome(paw_case, ["functions_are_real"])])
    one_medium = score([_outcome(paw_case, ["present"])])

    # Both are a 0% pass rate; only quality distinguishes them.
    assert one_critical["pass_rate"] == one_medium["pass_rate"] == 0.0
    assert one_critical["quality"] < one_medium["quality"]


def test_a_critical_failure_dominates_many_low_ones(paw_case):
    critical = score([_outcome(paw_case, ["functions_are_real"])])
    several_medium = score([_outcome(paw_case, ["present"]) for _ in range(5)])

    assert critical["quality"] < several_medium["quality"]


def test_a_clean_run_scores_one(paw_case):
    clean = outcome_for(paw_case, [CheckResult("present", True)])

    result = score([clean])

    assert result["pass_rate"] == 1.0
    assert result["quality"] == 1.0


def test_failures_are_counted_by_severity(paw_case):
    result = score(
        [
            _outcome(paw_case, ["functions_are_real"]),
            _outcome(paw_case, ["present"]),
        ]
    )

    assert result["failures_by_severity"]["critical"] == 1
    assert result["failures_by_severity"]["medium"] == 1


def test_empty_run_does_not_divide_by_zero():
    assert score([])["quality"] == 0.0


def test_severity_weights_are_ordered_worst_first():
    weights = list(SEVERITY_WEIGHTS.values())

    assert weights == sorted(weights, reverse=True)
