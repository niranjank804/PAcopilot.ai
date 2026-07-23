import uuid
from unittest.mock import MagicMock

import pytest
from TM1py.Exceptions import TM1pyRestException

from src.tm1.exceptions import TM1NotFoundError
from src.tm1.services.security_service import get_group, list_groups


@pytest.mark.asyncio
async def test_list_groups_returns_names():
    client = MagicMock()
    client.security.get_all_groups.return_value = ["ADMIN", "Planners"]

    names = await list_groups(client, uuid.uuid4())

    assert names == ["ADMIN", "Planners"]
    client.security.get_all_groups.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_group_maps_to_group_info():
    client = MagicMock()
    client.security.get_user_names_from_group.return_value = ["alice", "bob"]

    info = await get_group(client, uuid.uuid4(), "Planners")

    assert info.name == "Planners"
    assert info.member_user_names == ["alice", "bob"]
    client.security.get_user_names_from_group.assert_called_once_with("Planners")


@pytest.mark.asyncio
async def test_get_group_raises_not_found_on_404():
    client = MagicMock()
    client.security.get_user_names_from_group.side_effect = TM1pyRestException(
        response="not found", status_code=404, reason="Not Found", headers={}
    )

    with pytest.raises(TM1NotFoundError):
        await get_group(client, uuid.uuid4(), "Missing")
