import uuid
from unittest.mock import MagicMock

import pytest
from TM1py.Exceptions import TM1pyRestException

from src.tm1.exceptions import TM1ConnectionError, TM1NotFoundError
from src.tm1.services.cube_service import get_cube, list_cubes


@pytest.mark.asyncio
async def test_list_cubes_returns_names():
    client = MagicMock()
    client.cubes.get_all_names.return_value = ["Sales", "Budget"]

    names = await list_cubes(client, uuid.uuid4())

    assert names == ["Sales", "Budget"]
    client.cubes.get_all_names.assert_called_once_with(skip_control_cubes=True)


@pytest.mark.asyncio
async def test_get_cube_maps_to_cube_info():
    fake_cube = MagicMock()
    fake_cube.name = "Sales"
    fake_cube.dimensions = ["Region", "Product"]
    fake_cube.has_rules = True

    client = MagicMock()
    client.cubes.get.return_value = fake_cube

    info = await get_cube(client, uuid.uuid4(), "Sales")

    assert info.name == "Sales"
    assert info.dimensions == ["Region", "Product"]
    assert info.has_rules is True


@pytest.mark.asyncio
async def test_get_cube_raises_not_found_on_404():
    client = MagicMock()
    client.cubes.get.side_effect = TM1pyRestException(
        response="not found", status_code=404, reason="Not Found", headers={}
    )

    with pytest.raises(TM1NotFoundError):
        await get_cube(client, uuid.uuid4(), "Missing")


@pytest.mark.asyncio
async def test_get_cube_raises_connection_error_on_persistent_server_error():
    client = MagicMock()
    client.cubes.get.side_effect = TM1pyRestException(
        response="server error", status_code=500, reason="Server Error", headers={}
    )

    with pytest.raises(TM1ConnectionError):
        await get_cube(client, uuid.uuid4(), "Sales", max_retries=0)
