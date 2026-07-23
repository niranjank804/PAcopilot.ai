import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class ChoreInfo:

    def __init__(
        self,
        name: str,
        active: bool,
        process_names: list[str],
    ):
        self.name = name
        self.active = active
        self.process_names = process_names


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
    )
