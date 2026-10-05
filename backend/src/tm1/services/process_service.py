import time
import uuid

from TM1py import TM1Service

from src.tm1 import compat
from src.tm1.resilience import call_with_resilience

# Keyword names TM1py's ExecuteWithReturn takes for itself. A TI parameter
# with one of these names cannot be passed as a keyword without silently
# changing how TM1py runs the call, so it is refused instead.
RESERVED_RUN_KEYWORDS = frozenset(
    {"process_name", "timeout", "cancel_at_timeout", "return_async_id", "retry_on_disconnect"}
)


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
        parameters: list[dict] | None = None,
        variables: list[dict] | None = None,
        datasource: dict | None = None,
    ):
        self.name = name
        # Name, type ("Numeric"/"String"), default value and prompt.
        self.parameters = parameters or []
        # Name and type of each datasource variable.
        self.variables = variables or []
        # ASCII settings and the like; empty for a process with no source.
        self.datasource = datasource or {}
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
        parameters=_parameters(process),
        variables=_variables(process),
        datasource=_datasource(process),
    )


def _parameters(process) -> list[dict]:
    found = []

    for parameter in process.parameters or []:
        if not isinstance(parameter, dict):
            continue
        found.append(
            {
                "name": parameter.get("Name", ""),
                "type": parameter.get("Type", ""),
                "default": parameter.get("Value"),
                "prompt": parameter.get("Prompt", ""),
            }
        )

    return found


def _variables(process) -> list[dict]:
    found = []

    for variable in process.variables or []:
        if not isinstance(variable, dict):
            continue
        found.append({"name": variable.get("Name", ""), "type": variable.get("Type", "")})

    return found


def _datasource(process) -> dict:
    kind = (process.datasource_type or "None")

    if kind == "ASCII":
        return {
            "delimiter_type": getattr(process, "datasource_ascii_delimiter_type", None),
            "delimiter": getattr(process, "datasource_ascii_delimiter_char", None),
            "quote_character": getattr(process, "datasource_ascii_quote_character", None),
            "header_records": getattr(process, "datasource_ascii_header_records", None),
            "decimal_separator": getattr(process, "datasource_ascii_decimal_separator", None),
            "thousand_separator": getattr(process, "datasource_ascii_thousand_separator", None),
        }

    return {}


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


async def search_process_code(
    client: TM1Service,
    connection_id: uuid.UUID,
    search_string: str,
    **resilience_kwargs,
) -> list[str]:
    """Names of processes whose code contains search_string (case-insensitive).

    TM1py pushes this down to the server rather than fetching every process,
    which matters on a model with hundreds of them.
    """

    matches = await call_with_resilience(
        connection_id,
        client.processes.search_string_in_code,
        search_string=search_string,
        skip_control_processes=True,
        **resilience_kwargs,
    )
    return matches or []


async def execute_process(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str,
    parameters: dict,
    timeout: float,
) -> dict:
    """Run a process once and report what TM1 said.

    Only ever reached from change_service.execute_change for an approved
    `run_process` draft. Never retried: a run is not idempotent, and a
    retry after a timeout could run a data load twice. TM1py's own
    timeout ends the request and asks TM1 to cancel the run.
    """

    reserved = RESERVED_RUN_KEYWORDS.intersection(parameters)

    if reserved:
        raise ValueError(
            "These parameter names clash with the TM1 API and cannot be "
            f"passed: {', '.join(sorted(reserved))}."
        )

    def run():
        try:
            success, status, error_log_file = client.processes.execute_with_return(
                process_name=process_name, timeout=timeout, cancel_at_timeout=True, **parameters
            )
            return success, status, error_log_file, None
        except Exception as exc:
            if not compat.is_unsupported_action(exc, "ExecuteWithReturn"):
                raise
        # An older server (TM1 11.0) has no ExecuteWithReturn; the run has
        # not started. tm1.Execute answers 204 on success and raises with the
        # outcome and TM1's error text otherwise.
        try:
            client.processes.execute(process_name, timeout=timeout, cancel_at_timeout=True, **parameters)
            return True, "CompletedSuccessfully", None, None
        except Exception as exc:
            outcome = compat.run_outcome(exc)
            if outcome is None:
                raise
            return False, outcome[0], None, outcome[1]

    # The resilience layer logs the callable's name on failure; the name
    # alone is enough (parameter values stay out of the log).
    run.__name__ = "execute_with_return"

    started = time.monotonic()
    success, status, error_log_file, error_detail = await call_with_resilience(
        connection_id, run, timeout=timeout, max_retries=0
    )

    result = {
        "success": bool(success),
        "status": status or ("CompletedSuccessfully" if success else "Unknown"),
        "error_log_file": error_log_file or None,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if error_detail:
        result["error_detail"] = error_detail[:2000]
    return result
