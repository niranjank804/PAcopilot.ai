import pytest

from src.tm1.service import tm1_integration_service


@pytest.mark.asyncio
async def test_list_cubes_returns_real_cube_names(db_session, live_connection):
    org, user, connection = live_connection

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)

    assert isinstance(cubes, list)
    assert all(isinstance(name, str) for name in cubes)


@pytest.mark.asyncio
async def test_get_cube_returns_real_shape(db_session, live_connection):
    org, user, connection = live_connection

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)

    if not cubes:
        pytest.skip("No cubes in this model to validate get_cube against.")

    cube = await tm1_integration_service.get_cube(
        db_session, connection.id, org.id, cubes[0]
    )

    assert cube.name == cubes[0]
    assert isinstance(cube.dimensions, list)
    assert all(isinstance(name, str) for name in cube.dimensions)
    assert isinstance(cube.has_rules, bool)


@pytest.mark.asyncio
async def test_list_dimensions_returns_real_dimension_names(
    db_session, live_connection
):
    org, user, connection = live_connection

    dimensions = await tm1_integration_service.list_dimensions(
        db_session, connection.id, org.id
    )

    assert isinstance(dimensions, list)
    assert all(isinstance(name, str) for name in dimensions)


@pytest.mark.asyncio
async def test_get_dimension_returns_real_shape(db_session, live_connection):
    org, user, connection = live_connection

    dimensions = await tm1_integration_service.list_dimensions(
        db_session, connection.id, org.id
    )

    if not dimensions:
        pytest.skip("No dimensions in this model to validate get_dimension against.")

    dimension = await tm1_integration_service.get_dimension(
        db_session, connection.id, org.id, dimensions[0]
    )

    assert dimension.name == dimensions[0]
    assert isinstance(dimension.hierarchy_names, list)
    assert len(dimension.hierarchy_names) >= 1


@pytest.mark.asyncio
async def test_every_cube_dimension_is_a_real_dimension(db_session, live_connection):
    """Cross-check: every dimension a cube claims to use must actually
    exist in the model's dimension list — validates the assumption
    src/tm1/metadata/extractor.py relies on when building uses_dimension
    edges."""

    org, user, connection = live_connection

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)
    dimensions = set(
        await tm1_integration_service.list_dimensions(db_session, connection.id, org.id)
    )

    for cube_name in cubes[:10]:
        cube = await tm1_integration_service.get_cube(
            db_session, connection.id, org.id, cube_name
        )

        for dimension_name in cube.dimensions:
            assert dimension_name in dimensions, (
                f"Cube '{cube_name}' references dimension '{dimension_name}' "
                "which is not in the model's dimension list"
            )
