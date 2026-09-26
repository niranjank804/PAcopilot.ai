import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.tm1.services.query_context import cube_query_context

# Workforce Planning Summary, shaped like the model where the analyst's
# unpinned queries all came back empty.
LEVELS = {"Version": 2, "Period": 3, "Center WFP": 4, "WFP Account": 3}
TOP = {
    "Version": ["Actual", "Forecast", "Plan"],
    "Period": ["All Periods"],
    "Center WFP": ["Center Alloc Hiers"],
    "WFP Account": ["Total Head Count", "Total Cost"],
}
DEFAULTS = {"Version": "Actual", "Period": "202601", "Center WFP": "C010000"}


def fake_client(default_member_fails: bool = False):
    client = MagicMock()
    client.cubes.get.return_value = SimpleNamespace(dimensions=list(LEVELS))
    client.elements.get_levels_count.side_effect = lambda d, h: LEVELS[d]
    client.elements.get_elements_by_level.side_effect = lambda d, h, level: (
        TOP[d] if level == LEVELS[d] - 1 else []
    )

    def default_member(d, h):
        if default_member_fails:
            raise RuntimeError("not supported on this server")
        return DEFAULTS.get(d)

    client.hierarchies.get_default_member.side_effect = default_member
    return client


@pytest.mark.asyncio
async def test_every_dimension_is_described_with_its_totals():
    context = await cube_query_context(
        fake_client(), uuid.uuid4(), "Workforce Planning Summary"
    )

    by_name = {d["name"]: d for d in context["dimensions"]}
    assert list(by_name) == ["Version", "Period", "Center WFP", "WFP Account"]
    assert by_name["Center WFP"]["top_elements"] == ["Center Alloc Hiers"]
    assert by_name["Center WFP"]["default_member"] == "C010000"
    # The top level is TM1's highest level, not level 0 (the leaves).
    assert by_name["WFP Account"]["top_elements"] == ["Total Head Count", "Total Cost"]


@pytest.mark.asyncio
async def test_where_pins_every_dimension_to_a_total_where_there_is_one():
    context = await cube_query_context(
        fake_client(), uuid.uuid4(), "Workforce Planning Summary"
    )

    where = context["where_all_totals"]
    # A single root is the total: preferred over a leaf default member.
    assert "[Center WFP].[Center WFP].[Center Alloc Hiers]" in where
    assert "[Period].[Period].[All Periods]" in where
    # Several roots (Actual, Forecast, Plan): the default member decides.
    assert "[Version].[Version].[Actual]" in where
    # No default member: the first root.
    assert "[WFP Account].[WFP Account].[Total Head Count]" in where
    assert where.startswith("WHERE (") and where.count("].[") == 8


@pytest.mark.asyncio
async def test_a_server_without_default_members_still_answers():
    context = await cube_query_context(
        fake_client(default_member_fails=True), uuid.uuid4(), "Workforce Planning Summary"
    )

    assert all(d["default_member"] is None for d in context["dimensions"])
    assert "[Version].[Version].[Actual]" in context["where_all_totals"]


def test_the_analyst_uses_it_and_has_room_to_recover():
    from src.ai.agents.registry import get_agent

    analyst = get_agent("analyst")
    assert "get_query_context" in analyst.tool_names
    assert analyst.max_tool_rounds >= 14
