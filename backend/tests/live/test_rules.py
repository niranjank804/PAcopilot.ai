import os

import pytest

from src.tm1.metadata.reference_parser import extract_rule_cube_references
from src.tm1.service import tm1_integration_service


@pytest.mark.asyncio
async def test_get_cube_rules_does_not_error_on_real_cubes_with_rules(
    db_session, live_connection
):
    org, user, connection = live_connection

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)

    checked = 0

    for cube_name in cubes[:25]:
        cube = await tm1_integration_service.get_cube(
            db_session, connection.id, org.id, cube_name
        )

        if not cube.has_rules:
            continue

        rules = await tm1_integration_service.get_cube_rules(
            db_session, connection.id, org.id, cube_name
        )

        assert rules is not None
        print(f"\n{cube_name}: {len(rules)} chars of rule text")
        checked += 1

    if checked == 0:
        pytest.skip("No cubes with rules in the first 25 to validate against.")


@pytest.mark.asyncio
async def test_reference_parser_against_a_known_real_rule_cube(
    db_session, live_connection
):
    """Optional deeper check: set TM1_TEST_CUBE_WITH_RULES to a cube name
    known to have non-trivial rules (comments, feeders, unusual
    formatting) to see exactly what the DB('...') heuristic extracts from
    real syntax, not synthetic test fixtures."""

    cube_name = os.environ.get("TM1_TEST_CUBE_WITH_RULES")

    if not cube_name:
        pytest.skip(
            "TM1_TEST_CUBE_WITH_RULES not set — skipping the reference-parser "
            "deep check (see docs/live_validation/CHECKLIST.md)."
        )

    org, user, connection = live_connection

    rules = await tm1_integration_service.get_cube_rules(
        db_session, connection.id, org.id, cube_name
    )

    assert rules is not None, f"'{cube_name}' has no rules — pick a different cube."

    referenced = extract_rule_cube_references(rules)

    print(f"\nCube references found by the heuristic in '{cube_name}': {referenced}")
