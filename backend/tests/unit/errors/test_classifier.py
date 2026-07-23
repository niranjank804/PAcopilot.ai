import pytest

from src.errors.classifier import classify_error


@pytest.mark.parametrize(
    "error_text,expected_type,expected_severity",
    [
        ("Error: Recursion level too deep in rule", "recursion", "high"),
        (
            "E10) Data directory not found: /tm1/data",
            "data_directory",
            "critical",
        ),
        (
            "Feeder statement produced too many leaf cells",
            "feeder_overflow",
            "medium",
        ),
        ("Could not logon: invalid credentials", "authentication", "high"),
        ("TI process failed with ProcessBreak", "process_failure", "medium"),
        ("Rule compilation error on line 4", "rule_error", "medium"),
        ("Server ran out of memory during rollup", "memory", "critical"),
        ("Operation timed out: deadlock detected", "lock", "medium"),
    ],
)
def test_classify_error_matches_known_patterns(
    error_text, expected_type, expected_severity
):
    result = classify_error(error_text)

    assert result.error_type == expected_type
    assert result.severity == expected_severity


def test_classify_error_falls_back_to_unknown():
    result = classify_error("Something completely unrelated happened")

    assert result.error_type == "unknown"
    assert result.severity == "unknown"


def test_classify_error_is_case_insensitive():
    result = classify_error("COULD NOT LOGON TO SERVER")

    assert result.error_type == "authentication"
