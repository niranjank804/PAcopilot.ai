import uuid
from unittest.mock import MagicMock

import pytest

from src.tm1.services.cell_service import MAX_CELLS, execute_mdx


@pytest.mark.asyncio
async def test_execute_mdx_returns_flat_cell_map():
    client = MagicMock()
    client.cubes.cells.execute_mdx_elements_value_dict.return_value = {
        "Jan-2026|Actual|Revenue": 125000.0,
        "Feb-2026|Actual|Revenue": 131000.0,
    }

    result = await execute_mdx(client, uuid.uuid4(), "SELECT ... FROM [Sales]")

    assert result.cells == {
        "Jan-2026|Actual|Revenue": 125000.0,
        "Feb-2026|Actual|Revenue": 131000.0,
    }


@pytest.mark.asyncio
async def test_execute_mdx_caps_result_size_via_top_argument():
    client = MagicMock()
    client.cubes.cells.execute_mdx_elements_value_dict.return_value = {}

    await execute_mdx(client, uuid.uuid4(), "SELECT ... FROM [Sales]")

    _, kwargs = client.cubes.cells.execute_mdx_elements_value_dict.call_args
    assert kwargs["top"] == MAX_CELLS
    assert kwargs["skip_zeros"] is True
