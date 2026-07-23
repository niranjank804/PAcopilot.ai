import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class DimensionInfo:

    def __init__(self, name: str, hierarchy_names: list[str]):
        self.name = name
        self.hierarchy_names = hierarchy_names


async def list_dimensions(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.dimensions.get_all_names,
        skip_control_dims=True,
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
