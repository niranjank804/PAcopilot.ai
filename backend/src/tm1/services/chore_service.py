import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class ChoreInfo:

    def __init__(
        self,
        name: str,
        active: bool,
        process_names: list[str],
        start_time: str | None = None,
        frequency: str | None = None,
        execution_mode: str | None = None,
        tasks: list[dict] | None = None,
    ):
        self.name = name
        self.active = active
        self.process_names = process_names
        # As TM1 stores them: an ISO start time and a DD:HH:MM:SS interval.
        self.start_time = start_time
        self.frequency = frequency
        # "SingleCommit" or "MultipleCommit".
        self.execution_mode = execution_mode
        # One entry per step, in order, with the parameter values it passes.
        self.tasks = tasks or []


async def list_chores(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.chores.get_all_names,
        **resilience_kwargs,
    )


async def get_chore(
    client: TM1Service,
    connection_id: uuid.UUID,
    chore_name: str,
    **resilience_kwargs,
) -> ChoreInfo:
    chore = await call_with_resilience(
        connection_id,
        client.chores.get,
        chore_name,
        **resilience_kwargs,
    )

    return ChoreInfo(
        name=chore.name,
        active=bool(chore.active),
        process_names=[task.process_name for task in chore.tasks],
        start_time=_text(getattr(chore, "start_time", None), "start_time_string"),
        frequency=_text(getattr(chore, "frequency", None), "frequency_string"),
        execution_mode=_plain(getattr(chore, "execution_mode", None)),
        tasks=[
            {
                "step": position + 1,
                "process": task.process_name,
                "parameters": [
                    {"name": p.get("Name"), "value": p.get("Value")}
                    for p in (getattr(task, "parameters", None) or [])
                    if isinstance(p, dict)
                ],
            }
            for position, task in enumerate(chore.tasks)
        ],
    )


def _plain(value) -> str | None:
    return value if isinstance(value, str) else None


def _text(value, attribute: str) -> str | None:
    """TM1py's schedule objects render themselves; anything else (a test
    double, a server that omits the field) is reported as absent rather
    than as a stringified object."""

    rendered = getattr(value, attribute, None) if value is not None else None

    return rendered if isinstance(rendered, str) else None
