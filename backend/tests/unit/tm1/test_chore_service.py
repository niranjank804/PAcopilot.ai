import uuid
from unittest.mock import MagicMock

import pytest
from TM1py.Exceptions import TM1pyRestException

from src.tm1.exceptions import TM1NotFoundError
from src.tm1.services.chore_service import get_chore, list_chores


def _make_task(process_name):
    task = MagicMock()
    task.process_name = process_name
    return task


@pytest.mark.asyncio
async def test_list_chores_returns_names():
    client = MagicMock()
    client.chores.get_all_names.return_value = ["Load Sales Nightly"]

    names = await list_chores(client, uuid.uuid4())

    assert names == ["Load Sales Nightly"]
    client.chores.get_all_names.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_chore_maps_to_chore_info():
    fake_chore = MagicMock()
    fake_chore.name = "Load Sales Nightly"
    fake_chore.active = True
    fake_chore.tasks = [_make_task("Load Sales"), _make_task("Load Expense")]

    client = MagicMock()
    client.chores.get.return_value = fake_chore

    info = await get_chore(client, uuid.uuid4(), "Load Sales Nightly")

    assert info.name == "Load Sales Nightly"
    assert info.active is True
    assert info.process_names == ["Load Sales", "Load Expense"]


@pytest.mark.asyncio
async def test_get_chore_raises_not_found_on_404():
    client = MagicMock()
    client.chores.get.side_effect = TM1pyRestException(
        response="not found", status_code=404, reason="Not Found", headers={}
    )

    with pytest.raises(TM1NotFoundError):
        await get_chore(client, uuid.uuid4(), "Missing")
