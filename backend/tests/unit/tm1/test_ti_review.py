"""The TI process review: what a reviewer is told, and why.

Each finding names the object, quotes the evidence, and says how sure it
is. These tests pin the findings a reviewer relies on most: dangerous
operations, writes without error handling, missing documentation, and the
complexity outliers.
"""

from src.tm1.ti.parser import parse_process_code
from src.tm1.ti.review import MAX_STATEMENTS, review


def _review(prolog="", data="", epilog="", parameters=None, **kwargs):
    record = parse_process_code(
        "zTest",
        prolog=prolog,
        metadata="",
        data=data,
        epilog=epilog,
        datasource_type="None",
        datasource_name="",
        parameters=parameters or [],
        variables=[],
    )
    return review(record, **kwargs)


def _categories(findings):
    return {f.category for f in findings}


def test_a_dangerous_operation_is_named_with_its_line():
    findings, _ = _review(prolog="# Clear before load\nCubeClearData('Sales');\n")

    danger = [f for f in findings if f.category == "danger"]
    assert danger, findings
    assert "CubeClearData" in danger[0].evidence or "CUBECLEARDATA" in danger[0].evidence.upper()
    assert danger[0].object == "process:zTest"
    assert danger[0].confidence in ("high", "medium", "low")


def test_shutting_the_server_down_is_an_error_not_a_hint():
    findings, _ = _review(prolog="ServerShutdown(1);\n")

    assert any(f.category == "danger" and f.severity == "error" for f in findings)


def test_a_clean_short_process_has_no_danger_or_complexity_findings():
    findings, metrics = _review(prolog="# Purpose: say hello\nsMsg = 'hello';\n")

    assert not ({"danger", "complexity"} & _categories(findings))
    assert metrics["statements"] < MAX_STATEMENTS


def test_an_undocumented_parameter_is_reported():
    findings, _ = _review(
        prolog="# Load\n" + "x = 1;\n" * 5,
        parameters=[{"name": "pYear", "type": "String", "prompt": ""}],
    )

    assert any(f.category == "documentation" and "pYear" in f.evidence for f in findings)


def test_a_long_prolog_without_a_header_comment_is_reported():
    findings, _ = _review(prolog="x = 1;\n" * 6)

    assert "documentation" in _categories(findings)


def test_a_very_long_process_is_flagged_as_complex():
    findings, metrics = _review(prolog="# Big\n" + "x = 1;\n" * (MAX_STATEMENTS + 5))

    assert metrics["statements"] > MAX_STATEMENTS
    assert "complexity" in _categories(findings)


def test_every_finding_carries_what_a_reviewer_needs():
    findings, _ = _review(prolog="CubeClearData('Sales');\nServerShutdown(1);\n" + "x = 1;\n" * 5)

    for finding in findings:
        data = finding.to_dict()
        for key in ("severity", "category", "object", "evidence", "reason", "recommendation", "confidence"):
            assert data[key], (key, data)
