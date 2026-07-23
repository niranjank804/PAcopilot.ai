import pytest

from src.tm1.service import tm1_integration_service


@pytest.mark.asyncio
async def test_list_processes_returns_real_process_names(db_session, live_connection):
    org, user, connection = live_connection

    processes = await tm1_integration_service.list_processes(
        db_session, connection.id, org.id
    )

    assert isinstance(processes, list)
    assert all(isinstance(name, str) for name in processes)


@pytest.mark.asyncio
async def test_get_process_returns_real_shape(db_session, live_connection):
    org, user, connection = live_connection

    processes = await tm1_integration_service.list_processes(
        db_session, connection.id, org.id
    )

    if not processes:
        pytest.skip("No processes in this model to validate get_process against.")

    process = await tm1_integration_service.get_process(
        db_session, connection.id, org.id, processes[0]
    )

    assert process.name == processes[0]
    assert isinstance(process.datasource_type, str)
    assert isinstance(process.has_security_access, bool)
    assert isinstance(process.parameter_names, list)
    assert isinstance(process.prolog, str)
    assert isinstance(process.metadata, str)
    assert isinstance(process.data, str)
    assert isinstance(process.epilog, str)


@pytest.mark.asyncio
async def test_datasource_types_seen_across_real_processes(db_session, live_connection):
    """Not an assertion so much as a survey: prints every distinct
    datasource_type this model's processes actually use, so a human can
    confirm the extractor/reference_parser handle all of them (the plan's
    'All datasource types' checklist row)."""

    org, user, connection = live_connection

    processes = await tm1_integration_service.list_processes(
        db_session, connection.id, org.id
    )

    datasource_types = set()

    for process_name in processes[:25]:
        process = await tm1_integration_service.get_process(
            db_session, connection.id, org.id, process_name
        )
        datasource_types.add(process.datasource_type)

    print(f"\nDistinct process datasource types seen: {sorted(datasource_types)}")
