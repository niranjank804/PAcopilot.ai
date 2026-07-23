import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience


class GroupInfo:

    def __init__(
        self,
        name: str,
        member_user_names: list[str],
    ):
        self.name = name
        self.member_user_names = member_user_names


async def list_groups(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.security.get_all_groups,
        **resilience_kwargs,
    )


async def get_group(
    client: TM1Service,
    connection_id: uuid.UUID,
    group_name: str,
    **resilience_kwargs,
) -> GroupInfo:
    member_user_names = await call_with_resilience(
        connection_id,
        client.security.get_user_names_from_group,
        group_name,
        **resilience_kwargs,
    )

    return GroupInfo(
        name=group_name,
        member_user_names=member_user_names,
    )
