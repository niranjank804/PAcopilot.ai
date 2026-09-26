"""MDX results as a table: one column per dimension, one row per cell.

The Visualize page used to receive a flat map of "Jan|Actual|Revenue" to
value, which can only ever be one series of bars with an unreadable label.
Keeping each dimension's member separate is what lets the page pivot the
same result — months on the axis, versions as the legend, a heatmap of
two dimensions — without asking the AI again.

Context (WHERE) members are left out of each row: they are the same for
every cell and are visible in the MDX.
"""

import re
import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

# Cells returned per query. Higher than the 500 the assistant's own tool
# reads, because the page pivots and aggregates rather than listing.
MAX_TABLE_CELLS = 2000

# "[Dim].[Hier].[Elem]" (v11 with hierarchies, v12) or "[Dim].[Elem]".
# "]]" is an escaped "]" inside a name.
_PART = r"\[((?:[^\]]|\]\])+)\]"
_UNIQUE_NAME = re.compile(rf"^{_PART}(?:\.{_PART})?\.{_PART}$")


def parse_unique_name(unique_name: str) -> tuple[str, str]:
    """(dimension label, element) from a TM1 member unique name.

    The label is the dimension, or "Dimension:Hierarchy" when a
    hierarchy other than the dimension's own is on an axis.
    """

    match = _UNIQUE_NAME.match(unique_name.strip())

    if not match:
        return "", unique_name

    dimension, hierarchy, element = (
        part.replace("]]", "]") if part else part for part in match.groups()
    )
    label = dimension if not hierarchy or hierarchy == dimension else f"{dimension}:{hierarchy}"

    return label, element


def to_table(cellset: dict, limit: int = MAX_TABLE_CELLS) -> dict:
    """A TM1py `execute_mdx` result as {dimensions, rows, truncated}."""

    dimensions: list[str] = []
    rows: list[dict] = []

    for key, properties in cellset.items():
        if len(rows) >= limit:
            break

        members: dict[str, str] = {}

        for unique_name in key if isinstance(key, tuple) else (key,):
            dimension, element = parse_unique_name(str(unique_name))
            label = dimension or f"Axis {len(members) + 1}"

            if label not in dimensions:
                dimensions.append(label)

            members[label] = element

        value = properties.get("Value") if isinstance(properties, dict) else properties

        rows.append({"members": members, "value": value})

    return {
        "dimensions": dimensions,
        "rows": rows,
        "truncated": len(cellset) > limit,
    }


async def execute_mdx_table(
    client: TM1Service,
    connection_id: uuid.UUID,
    mdx: str,
    **resilience_kwargs,
) -> dict:
    """Run read-only MDX and return it as a table."""

    cellset = await call_with_resilience(
        connection_id,
        client.cubes.cells.execute_mdx,
        mdx,
        cell_properties=["Value"],
        top=MAX_TABLE_CELLS + 1,
        skip_zeros=True,
        skip_contexts=True,
        element_unique_names=True,
        **resilience_kwargs,
    )

    return to_table(dict(cellset or {}))


def flat_cells(table: dict) -> dict[str, float | str | None]:
    """The old "a|b|c" -> value map, for callers that still read it."""

    return {
        "|".join(row["members"].get(d, "") for d in table["dimensions"]): row["value"]
        for row in table["rows"]
    }
