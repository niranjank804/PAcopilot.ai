"""find_data and query_cube against a small fake cube.

The fake evaluates the MDX these functions generate the way TM1 would: a
consolidated member is the sum of the leaves it rolls up (and a
consolidation can roll up nothing, like a zero-weighted total), NON EMPTY
drops empty tuples, and skip_zeros drops empty cells.
"""

import itertools
import re
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.tm1.services.query_builder import (
    QuerySpecError,
    build_mdx,
    find_data,
    query_cube,
)

MEMBER = re.compile(r"\[([^\]]+)\]\.\[[^\]]+\]\.\[([^\]]+)\]")
ALL = re.compile(r"TM1SUBSETALL\(\[([^\]]+)\]")


class FakeCube:
    def __init__(self, rollup, roots, defaults, data, children=None):
        # rollup[dim][element] -> the leaves it sums (a leaf: itself)
        self.rollup = rollup
        self.roots = roots
        self.defaults = defaults
        self.data = data  # list of ({dim: leaf}, value)
        self.children = children or {}
        self.dims = list(rollup)
        self.queries: list[str] = []

    def value(self, pins):
        return sum(
            v
            for coords, v in self.data
            if all(coords[d] in self.rollup[d][pins[d]] for d in pins)
        )

    def axis(self, text):
        found = ALL.search(text)
        if found:
            d = found.group(1)
            return d, list(self.rollup[d])
        members = MEMBER.findall(text)
        d = members[0][0]
        if ".Children" in text:
            return d, list(self.children[d][members[0][1]])
        return d, [e for _, e in members]

    def execute_mdx(self, mdx, **_):
        self.queries.append(mdx)
        where = {}
        if " WHERE (" in mdx:
            mdx, clause = mdx.split(" WHERE (", 1)
            where = dict(MEMBER.findall(clause))
        body = mdx.split(" FROM ")[0]
        axes = [self.axis(part) for part in re.split(r" ON \d,?", body) if "[" in part]

        cells = {}
        for combo in itertools.product(*[members for _, members in axes]):
            pins = dict(where)
            pins.update({d: e for (d, _), e in zip(axes, combo)})
            v = self.value(pins)
            if v:
                key = tuple(f"[{d}].[{d}].[{e}]" for (d, _), e in zip(axes, combo))
                cells[key] = {"Value": v}
        return cells

    def client(self):
        client = MagicMock()
        client.cubes.get.return_value = SimpleNamespace(dimensions=self.dims)
        client.elements.get_levels_count.side_effect = lambda d, h: 2
        client.elements.get_elements_by_level.side_effect = lambda d, h, level: (
            self.roots[d] if level == 1 else []
        )
        client.hierarchies.get_default_member.side_effect = lambda d, h: self.defaults.get(d)
        client.cubes.cells.execute_mdx.side_effect = self.execute_mdx
        return client


def workforce(**overrides):
    """Shaped like Workforce Planning Summary: headcount by centre."""

    rollup = {
        "Version": {"Actual": {"Actual"}, "Forecast": {"Forecast"}, "Plan": {"Plan"}},
        "Period": {"All Time": {"202501", "202502"}, "202501": {"202501"}, "202502": {"202502"}},
        "Currency": {"USD": {"USD"}, "Local": {"Local"}},
        "Center": {
            "Center Alloc Hiers": {"C010000", "C020201"},
            "C010000": {"C010000"},
            "C020201": {"C020201"},
        },
        "Account": {"Total Head Count": {"HC"}, "HC": {"HC"}},
    }
    roots = {
        "Version": ["Actual", "Forecast", "Plan"],
        "Period": ["All Time"],
        "Currency": ["USD", "Local"],
        "Center": ["Center Alloc Hiers"],
        "Account": ["Total Head Count"],
    }
    defaults = {"Version": "Actual", "Currency": "USD"}
    data = [
        ({"Version": "Plan", "Period": "202501", "Currency": "Local", "Center": "C010000", "Account": "HC"}, 120),
        ({"Version": "Plan", "Period": "202502", "Currency": "Local", "Center": "C020201", "Account": "HC"}, 80),
    ]
    children = {"Center": {"Center Alloc Hiers": ["C010000", "C020201"]}}
    cube = FakeCube(rollup, roots, defaults, data, children)
    for key, value in overrides.items():
        setattr(cube, key, value)
    return cube


def test_build_mdx_puts_every_dimension_in_exactly_one_place():
    mdx, where = build_mdx(
        "Sales",
        ["Version", "Period", "Region"],
        {"dimension": "Period", "members": ["Jan", "Feb"]},
        [{"dimension": "Region", "level": "leaves"}],
        {"Version": "Plan", "Period": "All Time", "Region": "World"},
        {},
    )

    # Period is on an axis, so its pin is dropped rather than repeated —
    # the duplicate TM1 rejects with HTTP 400.
    assert where == {"Version": "Plan"}
    assert mdx == (
        "SELECT NON EMPTY {[Period].[Period].[Jan], [Period].[Period].[Feb]} ON 0, "
        "NON EMPTY {TM1FILTERBYLEVEL(TM1SUBSETALL([Region].[Region]), 0)} ON 1 "
        "FROM [Sales] WHERE ([Version].[Version].[Plan])"
    )


def test_build_mdx_refuses_a_dimension_the_cube_lacks_or_twice():
    with pytest.raises(QuerySpecError, match="no dimension Department"):
        build_mdx("Sales", ["Period"], {"dimension": "Department"}, None, {}, {})
    with pytest.raises(QuerySpecError, match="one axis"):
        build_mdx(
            "Sales", ["Period"], {"dimension": "Period"}, [{"dimension": "Period"}], {}, {}
        )


def test_by_default_an_axis_is_the_children_of_its_total():
    mdx, _ = build_mdx(
        "WFP", ["Center"], {"dimension": "Center"}, None, {}, {"Center": ["Center Alloc Hiers"]}
    )
    assert "{[Center].[Center].[Center Alloc Hiers].Children}" in mdx


@pytest.mark.asyncio
async def test_totals_that_hold_data_are_used_as_they_are():
    cube = workforce(defaults={"Version": "Plan", "Currency": "Local"})

    result = await find_data(cube.client(), uuid.uuid4(), "WFP")

    assert result["found"] is True
    assert result["changed"] == {}
    assert result["where_with_data"]["Version"] == "Plan"


@pytest.mark.asyncio
async def test_one_wrong_total_is_found_and_replaced():
    # Currency's default is right; only Version's (Actual) is empty.
    cube = workforce(defaults={"Version": "Actual", "Currency": "Local"})

    result = await find_data(cube.client(), uuid.uuid4(), "WFP")

    assert result["found"] is True
    assert result["changed"] == {"Version": {"from": "Actual", "to": "Plan"}}
    assert "Plan" in result["members_with_data"]["Version"]


@pytest.mark.asyncio
async def test_two_wrong_totals_are_found_together():
    # The screenshot's case: Actual is empty AND the currency total is USD
    # while the data is in Local. Freeing either one alone finds nothing.
    cube = workforce()

    result = await find_data(cube.client(), uuid.uuid4(), "WFP")

    assert result["found"] is True
    assert result["where_with_data"]["Version"] == "Plan"
    assert result["where_with_data"]["Currency"] == "Local"


@pytest.mark.asyncio
async def test_a_total_that_rolls_up_nothing_is_repaired():
    # "All Time" exists but its weights are zero: it holds nothing.
    cube = workforce(defaults={"Version": "Plan", "Currency": "Local"})
    cube.rollup["Period"]["All Time"] = set()

    result = await find_data(cube.client(), uuid.uuid4(), "WFP")

    assert result["found"] is True
    assert result["where_with_data"]["Period"] in {"202501", "202502"}


@pytest.mark.asyncio
async def test_fixed_filters_are_kept_and_an_empty_selection_is_reported():
    cube = workforce()

    result = await find_data(
        cube.client(), uuid.uuid4(), "WFP", {"Period": "202502", "Center": "C010000"}
    )

    # C010000 has no February headcount: nothing to find, and the fixed
    # members were never swapped for ones that do have data.
    assert result["found"] is False
    assert result["fixed"] == {"Period": "202502", "Center": "C010000"}
    assert "no data" in result["note"].lower()


@pytest.mark.asyncio
async def test_find_data_names_an_unknown_dimension():
    with pytest.raises(QuerySpecError, match="Department"):
        await find_data(workforce().client(), uuid.uuid4(), "WFP", {"Department": "x"})


@pytest.mark.asyncio
async def test_query_cube_charts_headcount_by_centre():
    cube = workforce()

    result = await query_cube(
        cube.client(),
        uuid.uuid4(),
        "WFP",
        columns={"dimension": "Center"},
        filters={"Version": "Plan", "Currency": "Local"},
    )

    assert result["mdx"].startswith(
        "SELECT NON EMPTY {[Center].[Center].[Center Alloc Hiers].Children} ON 0"
    )
    assert result["where"]["Account"] == "Total Head Count"
    values = {row["members"]["Center"]: row["value"] for row in result["table"]["rows"]}
    assert values == {"C010000": 120, "C020201": 80}


def test_visualize_reads_back_the_query_query_cube_ran():
    import json

    from src.ai.visualization import _mdx_from_query_cube

    mdx = 'SELECT NON EMPTY {[Center].[Center].[Total "A"].Children} ON 0 FROM [WFP]'
    summary = json.dumps({"mdx": mdx, "cell_count": 2})[:500]
    assert _mdx_from_query_cube(summary) == mdx
    # Cut off inside the MDX by the 500-character summary: not guessed at.
    assert _mdx_from_query_cube(json.dumps({"mdx": "SELECT " + "x" * 600})[:500]) is None


def test_the_analyst_has_the_query_tools():
    from src.ai.agents.registry import get_agent

    tools = get_agent("analyst").tool_names
    assert {"find_data", "query_cube", "show_chart"} <= set(tools)
