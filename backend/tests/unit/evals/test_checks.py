"""The eval checks must fail on the failure modes they exist to catch.

A check that passes everything is worse than no check: it reports green and
suppresses doubt. Each test below feeds a deliberately bad answer and
asserts the check rejects it.
"""

import pathlib

import pytest

from evals.checks import (
    check_absent,
    check_functions_are_real,
    check_present,
    check_qualified,
    extract_code,
)

GOLDEN = (
    pathlib.Path(__file__).resolve().parents[3]
    / "evals"
    / "cases"
    / "ti"
    / "paw_fixed_width_load.golden.md"
).read_text(encoding="utf-8")

QUALIFIERS = [
    "architect",
    "not supported",
    "unsupported",
    "not available",
    "avoid",
    "instead",
    "cannot",
    "rather than",
    "unlike",
]


# --------------------------------------------------------------------------
# The reference answer passes every deterministic check.
# --------------------------------------------------------------------------


def test_golden_answer_passes_all_checks():
    assert check_functions_are_real(GOLDEN, context="TI").passed
    assert check_present(GOLDEN, ["CharacterDelimited", "SUBST", "Architect"]).passed
    assert check_absent(GOLDEN, ["behave identically", "work the same way"]).passed
    assert check_qualified(GOLDEN, "PositionDelimited", QUALIFIERS).passed


# --------------------------------------------------------------------------
# Failure mode 1 — invents unsupported TI functions.
# --------------------------------------------------------------------------


def test_invented_function_is_rejected():
    answer = "```tm1\nsCol = SUBSTRING( v1, 1, 10 );\n```"

    result = check_functions_are_real(answer, context="TI")

    assert not result.passed
    assert "SUBSTRING" in result.detail


def test_excel_function_in_ti_is_rejected():
    answer = "```tm1\nnValue = DBRW( '<YourCube>', 'a', 'b' );\n```"

    result = check_functions_are_real(answer, context="TI")

    assert not result.passed
    assert "DBRW" in result.detail


def test_an_answer_with_no_code_is_rejected():
    result = check_functions_are_real("Use CharacterDelimited.", context="TI")

    assert not result.passed
    assert "no code block" in result.detail


# --------------------------------------------------------------------------
# Failure mode 2 — claims Architect and PAW behave identically.
# --------------------------------------------------------------------------


def test_equivalence_claim_is_rejected():
    answer = "PAW and Architect behave identically for fixed-width files."

    assert not check_absent(answer, ["behave identically"]).passed


# --------------------------------------------------------------------------
# Failure mode 3 — recommends PositionDelimited with no qualification.
# --------------------------------------------------------------------------


def test_unqualified_position_delimited_is_rejected():
    answer = (
        "Set DatasourceType to PositionDelimited and declare each column "
        "with its start and length. " + "Filler text. " * 60
    )

    result = check_qualified(answer, "PositionDelimited", QUALIFIERS)

    assert not result.passed


def test_qualified_position_delimited_is_accepted():
    answer = (
        "PositionDelimited is the Architect route and is not available in "
        "PAW Modeler, so use CharacterDelimited instead."
    )

    assert check_qualified(answer, "PositionDelimited", QUALIFIERS).passed


def test_a_distant_qualifier_does_not_rescue_the_mention():
    answer = (
        "Set DatasourceType to PositionDelimited. "
        + "Filler. " * 200
        + "Architect differs from PAW."
    )

    assert not check_qualified(
        answer, "PositionDelimited", QUALIFIERS, window=100
    ).passed


# --------------------------------------------------------------------------
# Failure mode 4 — omits the recommendation entirely.
# --------------------------------------------------------------------------


def test_missing_required_terms_is_rejected():
    answer = "Load the file and slice the columns."

    result = check_present(answer, ["CharacterDelimited", "SUBST"])

    assert not result.passed
    assert "CharacterDelimited" in result.detail


# --------------------------------------------------------------------------
# Code extraction.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fence", ["tm1", "ti", "", "text"])
def test_code_is_extracted_from_any_fence_label(fence):
    assert "SUBST" in extract_code(f"```{fence}\nsA = SUBST( v1, 1, 5 );\n```")


def test_prose_outside_code_blocks_is_not_scanned():
    # A function named only in prose must not be treated as code — the
    # answer explaining why NOT to use something would otherwise fail.
    answer = "Do not use DBRW here.\n\n```tm1\nsA = SUBST( v1, 1, 5 );\n```"

    assert check_functions_are_real(answer, context="TI").passed
