import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

# Cap on cells returned per MDX query — same discipline as MAX_ELEMENTS /
# MAX_NODES elsewhere: a wide-open ad hoc MDX tool can otherwise pull back
# an unbounded cellset.
MAX_CELLS = 500


class CellsetResult:

    def __init__(self, cells: dict[str, float]):
        self.cells = cells


async def execute_mdx(
    client: TM1Service,
    connection_id: uuid.UUID,
    mdx: str,
    **resilience_kwargs,
) -> CellsetResult:
    """Runs read-only MDX and returns a flat {element-path: value} map.

    Uses TM1py's *_elements_value_dict variant (keys are pipe-joined member
    names, e.g. "Jan-2026|Actual|Revenue") rather than the raw axis-indexed
    cellset — far simpler to turn into chart-ready rows, at the cost of
    losing axis structure for multi-series results (acceptable for a first
    version; see visualization module notes).
    """

    cells = await call_with_resilience(
        connection_id,
        client.cubes.cells.execute_mdx_elements_value_dict,
        mdx,
        top=MAX_CELLS,
        skip_zeros=True,
        **resilience_kwargs,
    )

    return CellsetResult(cells=dict(cells))


# Coordinates per call. Each becomes one tuple on the columns of a single
# MDX query, so this bounds the query size as well as the response.
MAX_COORDINATES = 50

# TM1's own view of a cell. RuleDerived and Consolidated are what make
# "is this number calculated?" a verified answer rather than a guess.
CELL_PROPERTIES = ["Value", "RuleDerived", "Consolidated", "Updateable"]

# Element-existence checks made to explain a failed read. Bounded because
# the explanation must not cost more than the question.
MAX_EXISTENCE_CHECKS = 60


def _escape(name: str) -> str:
    return name.replace("]", "]]")


def build_cells_mdx(cube_name: str, dimensions: list[str], coordinates: list[list[str]]) -> str:
    """One MDX query reading every coordinate, all dimensions on columns.

    Built here rather than with TM1py's `get_values`, which splits each
    coordinate string on a separator and so breaks on element names that
    contain it.
    """

    tuples = []

    for coordinate in coordinates:
        members = ", ".join(
            f"[{_escape(dimension)}].[{_escape(dimension)}].[{_escape(element)}]"
            for dimension, element in zip(dimensions, coordinate)
        )
        tuples.append(f"({members})")

    return f"SELECT {{{', '.join(tuples)}}} ON COLUMNS FROM [{_escape(cube_name)}]"


async def read_cells(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    coordinates: list[list[str]],
    **resilience_kwargs,
) -> dict:
    """Read cells by coordinate with TM1's cell properties.

    Returns `{"dimensions", "cells"}` or, when a coordinate names an
    element that does not exist, `{"dimensions", "invalid"}` naming each
    bad (dimension, element) — the read is refused rather than reported
    as zero, which is what an invalid intersection would otherwise look
    like.
    """

    from TM1py.Exceptions import TM1pyRestException

    def fetch() -> dict:
        dimensions = list(client.cubes.get_dimension_names(cube_name))

        wrong_length = [
            position
            for position, coordinate in enumerate(coordinates)
            if len(coordinate) != len(dimensions)
        ]

        if wrong_length:
            return {
                "dimensions": dimensions,
                "error": (
                    f"Coordinates {wrong_length} do not name one element per "
                    f"dimension. {cube_name} has {len(dimensions)} dimensions, "
                    "in this order."
                ),
            }

        mdx = build_cells_mdx(cube_name, dimensions, coordinates)

        try:
            cellset = client.cells.execute_mdx(
                mdx,
                cell_properties=CELL_PROPERTIES,
                element_unique_names=False,
            )
        except TM1pyRestException:
            invalid = []
            checks = 0
            seen = set()

            for coordinate in coordinates:
                for dimension, element in zip(dimensions, coordinate):
                    if (dimension, element) in seen or checks >= MAX_EXISTENCE_CHECKS:
                        continue
                    seen.add((dimension, element))
                    checks += 1

                    if not client.elements.exists(dimension, dimension, element):
                        invalid.append({"dimension": dimension, "element": element})

            if invalid:
                return {"dimensions": dimensions, "invalid": invalid}

            raise

        values = list(cellset.values())
        cells = []

        for position, coordinate in enumerate(coordinates):
            properties = cellset.get(tuple(coordinate))

            if properties is None and position < len(values):
                properties = values[position]

            properties = properties or {}
            cells.append(
                {
                    "coordinates": dict(zip(dimensions, coordinate)),
                    "value": properties.get("Value"),
                    "rule_derived": properties.get("RuleDerived"),
                    "consolidated": properties.get("Consolidated"),
                    "updateable": properties.get("Updateable"),
                }
            )

        return {"dimensions": dimensions, "cells": cells}

    return await call_with_resilience(connection_id, fetch, **resilience_kwargs)


async def write_cells(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    dimensions: list[str],
    values: list[tuple[list[str], float | str]],
    **resilience_kwargs,
) -> None:
    """Write values to leaf cells, all in one request.

    Only ever reached from change_service for an approved `write_cells`
    change, or its rollback writing the saved values back. Setting a value
    is idempotent, so the usual retry is safe.
    """

    def write() -> None:
        client.cells.write_values(
            cube_name,
            {tuple(coordinates): value for coordinates, value in values},
            dimensions=dimensions,
        )

    write.__name__ = "write_values"
    await call_with_resilience(connection_id, write, **resilience_kwargs)


async def read_attribute_values(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    element_name: str,
    attribute_names: list[str],
    **resilience_kwargs,
) -> dict:
    """An element's attribute values, from the attribute control cube.

    TM1 keeps attribute values in `}ElementAttributes_<dimension>`, one
    cell per (element, attribute). Reading them as cells is exactly what
    ATTRS/ATTRN do inside TM1.
    """

    if not attribute_names:
        return {}

    control_cube = f"}}ElementAttributes_{dimension_name}"
    result = await read_cells(
        client,
        connection_id,
        control_cube,
        [[element_name, attribute] for attribute in attribute_names],
        **resilience_kwargs,
    )

    return {
        cell["coordinates"].get(control_cube, ""): cell["value"]
        for cell in result.get("cells", [])
    }
