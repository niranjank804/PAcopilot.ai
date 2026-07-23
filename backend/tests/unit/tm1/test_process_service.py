import uuid
from unittest.mock import MagicMock

import pytest
from TM1py.Exceptions import TM1pyRestException

from src.tm1.exceptions import TM1NotFoundError
from src.tm1.services.process_service import get_process, list_processes


def _make_process(name):
    process = MagicMock()
    process.name = name
    process.datasource_type = "TM1CubeView"
    process.datasource_data_source_name_for_server = "Sales"
    process.datasource_view = "All Sales"
    process.has_security_access = False
    process.parameters = [
        {"Name": "pYear", "Prompt": "Year", "Value": "2026", "Type": 2},
    ]
    process.prolog_procedure = "# prolog"
    process.metadata_procedure = ""
    process.data_procedure = "CellPutN(1, 'Sales', 'NA');"
    process.epilog_procedure = ""
    return process


@pytest.mark.asyncio
async def test_list_processes_returns_names():
    client = MagicMock()
    client.processes.get_all_names.return_value = ["Load Sales", "Load FX"]

    names = await list_processes(client, uuid.uuid4())

    assert names == ["Load Sales", "Load FX"]
    client.processes.get_all_names.assert_called_once_with(
        skip_control_processes=True
    )


@pytest.mark.asyncio
async def test_get_process_maps_to_process_info():
    client = MagicMock()
    client.processes.get.return_value = _make_process("Load Sales")

    info = await get_process(client, uuid.uuid4(), "Load Sales")

    assert info.name == "Load Sales"
    assert info.datasource_type == "TM1CubeView"
    assert info.datasource_name == "Sales"
    assert info.datasource_view == "All Sales"
    assert info.has_security_access is False
    assert info.parameter_names == ["pYear"]
    assert info.prolog == "# prolog"
    assert info.data == "CellPutN(1, 'Sales', 'NA');"


@pytest.mark.asyncio
async def test_get_process_raises_not_found_on_404():
    client = MagicMock()
    client.processes.get.side_effect = TM1pyRestException(
        response="not found", status_code=404, reason="Not Found", headers={}
    )

    with pytest.raises(TM1NotFoundError):
        await get_process(client, uuid.uuid4(), "Missing")
