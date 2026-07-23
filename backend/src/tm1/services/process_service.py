import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class ProcessInfo:

    def __init__(
        self,
        name: str,
        datasource_type: str,
        datasource_name: str,
        datasource_view: str,
        has_security_access: bool,
        parameter_names: list[str],
        prolog: str,
        metadata: str,
        data: str,
        epilog: str,
    ):
        self.name = name
        self.datasource_type = datasource_type
        self.datasource_name = datasource_name
        self.datasource_view = datasource_view
        self.has_security_access = has_security_access
        self.parameter_names = parameter_names
        self.prolog = prolog
        self.metadata = metadata
        self.data = data
        self.epilog = epilog


async def list_processes(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.processes.get_all_names,
        skip_control_processes=True,
        **resilience_kwargs,
    )


async def get_process(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    **resilience_kwargs,
) -> ProcessInfo:
    process = await call_with_resilience(
        connection_id,
        client.processes.get,
        process_name,
        **resilience_kwargs,
    )

    return ProcessInfo(
        name=process.name,
        datasource_type=process.datasource_type or "None",
        datasource_name=process.datasource_data_source_name_for_server or "",
        datasource_view=process.datasource_view or "",
        has_security_access=bool(process.has_security_access),
        parameter_names=[p["Name"] for p in (process.parameters or [])],
        prolog=process.prolog_procedure or "",
        metadata=process.metadata_procedure or "",
        data=process.data_procedure or "",
        epilog=process.epilog_procedure or "",
    )


async def compile_process_dryrun(
    client: TM1Service,
    connection_id: uuid.UUID,
    process,
    **resilience_kwargs,
) -> list:
    """Validate an in-memory Process without persisting it. Returns the
    server's syntax-error list (empty = valid)."""

    return await call_with_resilience(
        connection_id,
        client.processes.compile_process,
        process,
        **resilience_kwargs,
    )


async def get_process_body(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    **resilience_kwargs,
) -> dict:
    """Full TM1py dict snapshot of a process (roundtrips via
    Process.from_dict) — ProcessInfo drops fields like variables, so
    rollback snapshots use this instead."""

    process = await call_with_resilience(
        connection_id,
        client.processes.get,
        process_name,
        **resilience_kwargs,
    )

    return process.body_as_dict


async def update_or_create_process(
    client: TM1Service,
    connection_id: uuid.UUID,
    process,
    **resilience_kwargs,
) -> None:
    # Writes are single-attempt: never blindly re-fire a failed write.
    await call_with_resilience(
        connection_id,
        client.processes.update_or_create,
        process,
        max_retries=0,
        **resilience_kwargs,
    )


async def delete_process(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    **resilience_kwargs,
) -> None:
    await call_with_resilience(
        connection_id,
        client.processes.delete,
        process_name,
        max_retries=0,
        **resilience_kwargs,
    )


async def compile_process_on_server(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    **resilience_kwargs,
) -> list:
    """Post-write syntax check of a persisted process (error list)."""

    return await call_with_resilience(
        connection_id,
        client.processes.compile,
        process_name,
        **resilience_kwargs,
    )


async def process_exists(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    **resilience_kwargs,
) -> bool:
    return await call_with_resilience(
        connection_id,
        client.processes.exists,
        process_name,
        **resilience_kwargs,
    )
