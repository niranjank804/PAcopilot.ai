import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class DimensionInfo:

    def __init__(self, name: str, hierarchy_names: list[str], element_counts: dict | None = None):
        self.name = name
        self.hierarchy_names = hierarchy_names
        # {hierarchy: {total, leaf, consolidated, string}} when asked for.
        self.element_counts = element_counts


async def list_dimensions(
    client: TM1Service,
    connection_id: uuid.UUID,
    include_control: bool = False,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.dimensions.get_all_names,
        skip_control_dims=not include_control,
        **resilience_kwargs,
    )


async def get_dimension(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    **resilience_kwargs,
) -> DimensionInfo:
    dimension = await call_with_resilience(
        connection_id,
        client.dimensions.get,
        dimension_name,
        **resilience_kwargs,
    )

    return DimensionInfo(
        name=dimension.name,
        hierarchy_names=list(dimension.hierarchy_names),
    )


# Hierarchies counted per request; a dimension with more lists the rest
# without counts.
MAX_COUNTED_HIERARCHIES = 5


async def count_elements(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_names: list[str],
    **resilience_kwargs,
) -> dict:
    """How many elements each hierarchy has, counted by the server.

    "How many elements does X have?" used to be answered by listing
    elements (capped at 200) or by trying several tools: about 70 seconds
    in the live accuracy run. TM1 counts them in one request each.
    """

    def count() -> dict:
        counts = {}
        for hierarchy in hierarchy_names[:MAX_COUNTED_HIERARCHIES]:
            counts[hierarchy] = {
                "total": client.elements.get_number_of_elements(dimension_name, hierarchy),
                "leaf": client.elements.get_number_of_leaf_elements(dimension_name, hierarchy),
                "consolidated": client.elements.get_number_of_consolidated_elements(dimension_name, hierarchy),
                "string": client.elements.get_number_of_string_elements(dimension_name, hierarchy),
            }
        return counts

    count.__name__ = "count_elements"
    return await call_with_resilience(connection_id, count, **resilience_kwargs)


MAX_ELEMENTS = 200


async def list_elements(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str | None = None,
    **resilience_kwargs,
) -> list[str]:
    """Real element names (e.g. actual period/account labels), capped at
    MAX_ELEMENTS — grounding for MDX generation, not a full dimension dump."""

    names = await call_with_resilience(
        connection_id,
        client.elements.get_element_names,
        dimension_name,
        hierarchy_name or dimension_name,
        **resilience_kwargs,
    )

    return list(names)[:MAX_ELEMENTS]
