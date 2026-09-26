"""What an MDX query must say about every dimension of a cube.

A TM1 query that leaves a dimension out reads that dimension's default
member — often the first element, which may be a blank leaf or an unused
code — and a query that is otherwise right returns no cells. The analyst
kept doing exactly that: axis dimensions on COLUMNS and ROWS, nothing in
WHERE, zero cells every time, until it ran out of tool rounds.

So before writing MDX the analyst gets, per dimension, the default member
and the top-level elements (usually the "Total ..." consolidations), plus
a WHERE clause that pins every dimension to a total. A query built from it
starts from data that exists and narrows from there.
"""

import asyncio
import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

# Top-level elements listed per dimension. A dimension with many roots is
# usually flat (every element is its own root); a few are enough to choose.
MAX_TOP_ELEMENTS = 8

# Default members are a nicety; an old server that cannot say must not
# slow the answer down or count against the connection's circuit breaker.
_DEFAULT_MEMBER_TIMEOUT = 10.0


def _member(dimension: str, element: str) -> str:
    escape = lambda name: name.replace("]", "]]")  # noqa: E731
    return f"[{escape(dimension)}].[{escape(dimension)}].[{escape(element)}]"


async def _default_member(client: TM1Service, dimension: str) -> str | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.hierarchies.get_default_member, dimension, dimension
            ),
            _DEFAULT_MEMBER_TIMEOUT,
        )
    except Exception:
        return None


async def _describe_dimension(
    client: TM1Service, connection_id: uuid.UUID, dimension: str
) -> dict:
    levels = await call_with_resilience(
        connection_id, client.elements.get_levels_count, dimension, dimension
    )
    top = (
        await call_with_resilience(
            connection_id,
            client.elements.get_elements_by_level,
            dimension,
            dimension,
            max(int(levels) - 1, 0),
        )
        if levels
        else []
    )
    default = await _default_member(client, dimension)

    return {
        "name": dimension,
        "default_member": default,
        "top_elements": list(top)[:MAX_TOP_ELEMENTS],
        "more_top_elements": max(len(top) - MAX_TOP_ELEMENTS, 0),
        "levels": int(levels or 0),
    }


async def cube_query_context(
    client: TM1Service, connection_id: uuid.UUID, cube_name: str
) -> dict:
    cube = await call_with_resilience(connection_id, client.cubes.get, cube_name)
    dimensions = list(cube.dimensions)

    described = await asyncio.gather(
        *(_describe_dimension(client, connection_id, d) for d in dimensions)
    )

    # A total where there is one, else the default member: the starting
    # point most likely to hold data.
    totals: dict[str, str] = {}
    for dimension in described:
        element = (
            dimension["top_elements"][0]
            if len(dimension["top_elements"]) == 1
            else dimension["default_member"]
            or (dimension["top_elements"] or [None])[0]
        )
        if element:
            totals[dimension["name"]] = element

    return {
        "cube": cube_name,
        "dimensions": described,
        "totals": totals,
        "where_all_totals": where_clause(totals),
    }


def where_clause(pins: dict[str, str]) -> str:
    members = [_member(dimension, element) for dimension, element in pins.items()]
    return f"WHERE ({', '.join(members)})" if members else ""
