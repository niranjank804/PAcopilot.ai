"""Reading a TM1 error log, and checking what it claims (phase 3).

The category is a reading of TM1's words; the checks are facts read from
TM1. These tests pin both: that common messages are recognised with the
names they carry, that unknown messages stay unclassified, and that a
check reports "still missing", "exists now" or "could not be checked" —
never a guess.
"""

from unittest.mock import MagicMock

import pytest

from src.tm1.diagnostics.failure import classify, findings_from_log, verify


@pytest.mark.parametrize(
    ("message", "category", "entities"),
    [
        (
            'Invalid key: Dimension Name: "Year", Element Name (Key): "2027"',
            "element_not_found",
            {"dimension": "Year", "element": "2027"},
        ),
        (
            'Element "Jan-27" not found in dimension "Month"',
            "element_not_found",
            {"element": "Jan-27", "dimension": "Month"},
        ),
        ('"ACME Ltd" : member not found', "element_not_found", {"element": "ACME Ltd"}),
        ('Cube "Sales Plan" not found', "object_not_found", {"kind": "cube", "name": "Sales Plan"}),
        ('Process "Load Rates" does not exist', "object_not_found", {"kind": "process", "name": "Load Rates"}),
        ('Cannot convert field number 3, value "n/a" to a real number.', "conversion", {"field": "3", "value": "n/a"}),
        (r"Unable to open data source C:\Data\actuals.csv", "data_source", {}),
        ("Cannot write to a consolidated element", "consolidated_write", {}),
        ("Cell is rule-derived and cannot be updated", "rule_derived", {}),
        ("Object is locked by another session", "security_or_lock", {}),
        ("ProcessQuit called in Prolog", "process_quit", {}),
    ],
)
def test_common_tm1_messages_are_recognised_with_their_names(message, category, entities):
    finding = classify(message)

    assert finding is not None, message
    assert finding.category == category
    for key, value in entities.items():
        assert finding.entities.get(key) == value, (key, finding.entities)
    assert finding.meaning and finding.fix_direction


def test_a_message_no_pattern_knows_stays_unclassified():
    assert classify("Something unusual happened at step 4") is None


def test_located_errors_keep_their_code_line_and_other_lines_are_scanned():
    locations = [
        {"section": "data", "line_number": 12,
         "message": 'Invalid key: Dimension Name: "Year", Element Name (Key): "2027"'},
        {"section": "data", "line_number": 13, "message": "Strange thing"},
    ]
    log = (
        "Error: Data procedure line (12): Invalid key: Dimension Name: \"Year\", Element Name (Key): \"2027\"\n"
        "Error: Data procedure line (13): Strange thing\n"
        "Unable to open data source C:\\feeds\\rates.csv\n"
    )

    findings, unclassified = findings_from_log(locations, log)

    categories = [f.category for f in findings]
    assert categories == ["element_not_found", "data_source"]
    assert findings[0].line_number == 12 and findings[0].section == "data"
    assert unclassified == ["Strange thing"]


def test_the_same_failure_on_many_lines_is_reported_once():
    message = 'Invalid key: Dimension Name: "Year", Element Name (Key): "2027"'
    locations = [{"section": "data", "line_number": 12, "message": message}] * 50

    findings, _ = findings_from_log(locations, "")

    assert len(findings) == 1


@pytest.mark.asyncio
async def test_a_missing_element_is_checked_against_the_model_now(monkeypatch):
    client = MagicMock()
    client.dimensions.exists.return_value = True
    client.elements.exists.return_value = False

    findings, _ = findings_from_log(
        [{"section": "data", "line_number": 1,
          "message": 'Invalid key: Dimension Name: "Year", Element Name (Key): "2027"'}],
        "",
    )
    await verify(client, None, findings)

    check = findings[0].checks[0]
    assert "2027" in check["check"] and "Year" in check["check"]
    assert check["result"].startswith("no — it is still missing")
    client.elements.exists.assert_called_once_with("Year", "Year", "2027")


@pytest.mark.asyncio
async def test_an_element_added_since_the_run_is_reported_as_existing_now():
    client = MagicMock()
    client.dimensions.exists.return_value = True
    client.elements.exists.return_value = True

    findings, _ = findings_from_log(
        [{"section": "data", "line_number": 1, "message": 'Element "2027" not found in dimension "Year"'}],
        "",
    )
    await verify(client, None, findings)

    assert findings[0].checks[0]["result"].startswith("yes — it exists now")


@pytest.mark.asyncio
async def test_a_check_that_fails_is_reported_as_not_made_never_as_a_result():
    client = MagicMock()
    client.cubes.exists.side_effect = RuntimeError("TM1 went away")

    findings, _ = findings_from_log(
        [{"section": "prolog", "line_number": 2, "message": 'Cube "Sales Plan" not found'}], ""
    )
    await verify(client, None, findings)

    assert findings[0].checks[0]["result"] == "could not be checked"
