"""Queries built from a structured request, and a search for where data is.

The analyst writing MDX by hand failed in two ways on a real cube: it put a
dimension on an axis and in WHERE at once (TM1 answers HTTP 400), and when
every dimension was pinned to its total the query was still empty, because
one of those "totals" does not roll the data up — and it had no quick way
to tell which. Both are mechanical, so they are done here:

- `build_mdx` places each dimension exactly once: on an axis, or in WHERE
  at the member asked for, or else at its total.
- `find_data` checks the totals; when they are empty it frees one
  dimension at a time (NON EMPTY over all its members, the others pinned)
  to find the pin that hides the data, and re-pins it to the member that
  holds the most. When two pins are wrong at once, it tries combinations
  of the top-level members of dimensions that have several (Actual/Plan,
  alternate roll-ups) — each a single-cell check — and repairs one more
  pin under the likeliest. It never asks for a cross join of whole
  dimensions: on a production server that can be expensive.
"""

import asyncio
import itertools
import uuid
from typing import Any

from TM1py import TM1Service

from src.tm1.services.mdx_table import execute_mdx_table
from src.tm1.services.query_context import cube_query_context, where_clause

# Cells asked for when probing one dimension: enough to rank its members.
_PROBE_CELLS = 200
# Members reported per dimension that turned out to hold data.
_MEMBERS_REPORTED = 12
# A probe is a question, not the answer: fail fast and move on.
_PROBE_TIMEOUT = 30.0
# The whole search. Past it, report what was tried instead of trying more.
_SEARCH_SECONDS = 90.0
# Combinations of top-level members tried as single-cell checks.
_MAX_COMBOS = 24
# Combinations under which one pin at a time is repaired.
_REPAIR_COMBOS = 4

LEVELS = ("leaves", "all", "top")


class QuerySpecError(ValueError):
    """The request names something the cube does not have, or asks twice."""


def _escape(name: str) -> str:
    return name.replace("]", "]]")


def member(dimension: str, element: str) -> str:
    d = _escape(dimension)
    return f"[{d}].[{d}].[{_escape(element)}]"


def axis_set(spec: dict, top_elements: dict[str, list[str]]) -> str:
    """The MDX set for one axis dimension.

    spec: {"dimension": d} plus one of
      "members": [e, ...]          exactly these
      "children_of": e             e's children
      "level": "leaves"|"all"|"top"
    Defaults to the children of the dimension's total, which is what "by
    department" usually means.
    """

    dimension = spec["dimension"]
    d = _escape(dimension)
    hierarchy = f"[{d}].[{d}]"

    if spec.get("members"):
        return "{" + ", ".join(member(dimension, e) for e in spec["members"]) + "}"
    if spec.get("children_of"):
        return "{" + f"{member(dimension, spec['children_of'])}.Children" + "}"

    level = spec.get("level")
    if level == "leaves":
        return f"{{TM1FILTERBYLEVEL(TM1SUBSETALL({hierarchy}), 0)}}"
    if level == "all":
        return f"{{TM1SUBSETALL({hierarchy})}}"
    if level == "top":
        tops = top_elements.get(dimension) or []
        if tops:
            return "{" + ", ".join(member(dimension, e) for e in tops) + "}"
        return f"{{TM1SUBSETALL({hierarchy})}}"

    tops = top_elements.get(dimension) or []
    if len(tops) == 1:
        return "{" + f"{member(dimension, tops[0])}.Children" + "}"
    if tops:
        return "{" + ", ".join(member(dimension, e) for e in tops) + "}"
    return f"{{TM1SUBSETALL({hierarchy})}}"


def build_mdx(
    cube: str,
    dimensions: list[str],
    columns: dict,
    rows: list[dict] | None,
    pins: dict[str, str],
    top_elements: dict[str, list[str]],
) -> tuple[str, dict[str, str]]:
    """(mdx, the WHERE pins used). Every dimension appears exactly once."""

    rows = rows or []
    axis_dims = [columns["dimension"], *(r["dimension"] for r in rows)]

    unknown = [d for d in axis_dims + list(pins) if d not in dimensions]
    if unknown:
        raise QuerySpecError(
            f"The cube {cube} has no dimension {', '.join(sorted(set(unknown)))}. "
            f"Its dimensions are: {', '.join(dimensions)}."
        )
    if len(set(axis_dims)) != len(axis_dims):
        raise QuerySpecError("A dimension can be on one axis only.")

    # An axis dimension is never also in WHERE — the HTTP 400 this exists
    # to prevent.
    where = {d: e for d, e in pins.items() if d not in axis_dims}

    mdx = f"SELECT NON EMPTY {axis_set(columns, top_elements)} ON 0"
    if rows:
        row_set = " * ".join(axis_set(r, top_elements) for r in rows)
        mdx += f", NON EMPTY {row_set} ON 1"
    mdx += f" FROM [{_escape(cube)}]"
    clause = where_clause(where)
    if clause:
        mdx += f" {clause}"

    return mdx, where


async def _run(client, connection_id, mdx: str, *, probe: bool = False) -> dict:
    if probe:
        return await execute_mdx_table(
            client, connection_id, mdx, timeout=_PROBE_TIMEOUT, max_retries=0
        )
    return await execute_mdx_table(client, connection_id, mdx)


def _magnitude(value: Any) -> float:
    return abs(value) if isinstance(value, (int, float)) else 0.0


def _ranked_members(table: dict, dimension: str) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in table["rows"]:
        element = row["members"].get(dimension)
        if element is not None:
            totals[element] = totals.get(element, 0.0) + _magnitude(row["value"])
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


async def find_data(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube: str,
    filters: dict[str, str] | None = None,
) -> dict:
    filters = dict(filters or {})
    context = await cube_query_context(client, connection_id, cube)
    dimensions = [d["name"] for d in context["dimensions"]]

    unknown = [d for d in filters if d not in dimensions]
    if unknown:
        raise QuerySpecError(
            f"The cube {cube} has no dimension {', '.join(unknown)}. "
            f"Its dimensions are: {', '.join(dimensions)}."
        )

    base = {**context["totals"], **filters}
    free = [d for d in dimensions if d not in filters]
    roots = {d["name"]: d["top_elements"] for d in context["dimensions"]}
    deadline = asyncio.get_running_loop().time() + _SEARCH_SECONDS
    members_with_data: dict[str, list[str]] = {}

    def out_of_time() -> bool:
        return asyncio.get_running_loop().time() > deadline

    async def has_data(current: dict[str, str]) -> bool:
        # One cell: every dimension at its pin.
        anchor = next(iter(current), dimensions[0])
        mdx, _ = build_mdx(
            cube,
            dimensions,
            {"dimension": anchor, "members": [current[anchor]]},
            None,
            current,
            {},
        )
        try:
            return bool((await _run(client, connection_id, mdx, probe=True))["rows"])
        except Exception:
            return False

    async def repair_one_pin(current: dict[str, str]) -> dict[str, str] | None:
        """Free one dimension at a time (all its members, the rest pinned).
        A probe that finds data names the pin that was hiding it."""
        for dimension in free:
            if out_of_time():
                return None
            others = {d: e for d, e in current.items() if d != dimension}
            mdx, _ = build_mdx(
                cube,
                dimensions,
                {"dimension": dimension, "level": "all"},
                None,
                others,
                {},
            )
            try:
                table = await _run(client, connection_id, mdx, probe=True)
            except Exception:
                continue
            ranked = _ranked_members(table, dimension)
            if ranked:
                members_with_data[dimension] = [
                    m for m, _ in ranked[:_MEMBERS_REPORTED]
                ]
                return {**current, dimension: ranked[0][0]}
        return None

    def found(pins: dict[str, str], how: str) -> dict:
        changed = {
            d: {"from": base.get(d), "to": e}
            for d, e in pins.items()
            if base.get(d) != e
        }
        return {
            "cube": cube,
            "fixed": filters,
            "found": True,
            "where_with_data": pins,
            "changed": changed,
            "members_with_data": members_with_data,
            "note": how,
        }

    # 1. The totals.
    if await has_data(base):
        return found(base, "The totals hold data; query from here.")

    # 2. One wrong total.
    repaired = await repair_one_pin(base)
    if repaired and await has_data(repaired):
        return found(repaired, "One total held no data; where_with_data replaces it.")

    # 3. Several at once. Dimensions with more than one top-level element
    #    (Actual/Plan/Forecast, alternate roll-ups) are where a "total" is
    #    a guess; try their combinations — each try is a single cell.
    ambiguous = [d for d in free if len(roots.get(d) or []) > 1]
    choices = [
        [base[d], *[r for r in roots[d] if r != base.get(d)]] if d in base else roots[d]
        for d in ambiguous
    ]
    combos = (
        [
            {**base, **dict(zip(ambiguous, combo))}
            for combo in itertools.islice(itertools.product(*choices), _MAX_COMBOS)
        ]
        if ambiguous
        else []
    )

    for trial in combos[1:]:
        if out_of_time():
            break
        if await has_data(trial):
            return found(trial, "A different top-level member holds the data.")

    # 4. Several wrong, one of them not ambiguous: repair one pin under the
    #    likeliest combinations.
    for trial in combos[:_REPAIR_COMBOS]:
        if out_of_time():
            break
        repaired = await repair_one_pin(trial)
        if repaired and await has_data(repaired):
            return found(
                repaired, "Two pins held no data; where_with_data replaces them."
            )

    return {
        "cube": cube,
        "fixed": filters,
        "found": False,
        "where_with_data": None,
        "changed": {},
        "members_with_data": members_with_data,
        "top_elements": {d: roots.get(d) for d in dimensions},
        "note": (
            "No combination of totals tried holds data"
            + (" for the fixed members" if filters else "")
            + ". Tell the person plainly that no data was found for this "
            "selection, and which members were tried — do not guess further "
            "element names."
        ),
    }


async def query_cube(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube: str,
    columns: dict,
    rows: list[dict] | None = None,
    filters: dict[str, str] | None = None,
) -> dict:
    context = await cube_query_context(client, connection_id, cube)
    dimensions = [d["name"] for d in context["dimensions"]]
    top_elements = {d["name"]: d["top_elements"] for d in context["dimensions"]}

    pins = {**context["totals"], **(filters or {})}
    mdx, where = build_mdx(cube, dimensions, columns, rows, pins, top_elements)
    table = await _run(client, connection_id, mdx)

    return {"mdx": mdx, "where": where, "table": table}
