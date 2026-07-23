import uuid
from unittest.mock import MagicMock

import pytest
from TM1py.Exceptions import TM1pyRestException

from src.tm1.exceptions import TM1NotFoundError
from src.tm1.services.dimension_service import (
    MAX_ELEMENTS,
    get_dimension,
    list_dimensions,
    list_elements,
)


@pytest.mark.asyncio
async def test_list_dimensions_returns_names():
    client = MagicMock()
    client.dimensions.get_all_names.return_value = ["Region", "Product"]

    names = await list_dimensions(client, uuid.uuid4())

    assert names == ["Region", "Product"]
    client.dimensions.get_all_names.assert_called_once_with(skip_control_dims=True)


@pytest.mark.asyncio
async def test_get_dimension_maps_to_dimension_info():
    fake_dimension = MagicMock()
    fake_dimension.name = "Region"
    fake_dimension.hierarchy_names = ["Region", "Region Alt"]

    client = MagicMock()
    client.dimensions.get.return_value = fake_dimension

    info = await get_dimension(client, uuid.uuid4(), "Region")

    assert info.name == "Region"
    assert info.hierarchy_names == ["Region", "Region Alt"]


@pytest.mark.asyncio
async def test_get_dimension_raises_not_found_on_404():
    client = MagicMock()
    client.dimensions.get.side_effect = TM1pyRestException(
        response="not found", status_code=404, reason="Not Found", headers={}
    )

    with pytest.raises(TM1NotFoundError):
        await get_dimension(client, uuid.uuid4(), "Missing")


@pytest.mark.asyncio
async def test_list_elements_returns_names_from_default_hierarchy():
    client = MagicMock()
    client.elements.get_element_names.return_value = ["Jan-2026", "Feb-2026"]

    names = await list_elements(client, uuid.uuid4(), "Period")

    assert names == ["Jan-2026", "Feb-2026"]
    client.elements.get_element_names.assert_called_once_with("Period", "Period")


@pytest.mark.asyncio
async def test_list_elements_uses_explicit_hierarchy_name():
    client = MagicMock()
    client.elements.get_element_names.return_value = ["A"]

    await list_elements(client, uuid.uuid4(), "Period", "Period Alt")

    client.elements.get_element_names.assert_called_once_with(
        "Period", "Period Alt"
    )


@pytest.mark.asyncio
async def test_list_elements_caps_at_max_elements():
    client = MagicMock()
    client.elements.get_element_names.return_value = [
        f"E{i}" for i in range(MAX_ELEMENTS + 50)
    ]

    names = await list_elements(client, uuid.uuid4(), "Big")

    assert len(names) == MAX_ELEMENTS
