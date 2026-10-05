import uuid

from TM1py import TM1Service

from src.tm1 import compat
from src.tm1.resilience import call_with_resilience


class CubeInfo:

    def __init__(self, name: str, dimensions: list[str], has_rules: bool):
        self.name = name
        self.dimensions = dimensions
        self.has_rules = has_rules


async def list_cubes(
    client: TM1Service,
    connection_id: uuid.UUID,
    include_control: bool = False,
    **resilience_kwargs,
) -> list[str]:
    # Control cubes (}ClientGroups, }ElementAttributes_…, }Stats…) are
    # hidden unless asked for: they are noise in "what cubes are there" and
    # the evidence in "why can this user not see that".
    return await call_with_resilience(
        connection_id,
        client.cubes.get_all_names,
        skip_control_cubes=not include_control,
        **resilience_kwargs,
    )


async def get_cube(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    **resilience_kwargs,
) -> CubeInfo:
    cube = await call_with_resilience(
        connection_id,
        client.cubes.get,
        cube_name,
        **resilience_kwargs,
    )

    return CubeInfo(
        name=cube.name,
        dimensions=list(cube.dimensions),
        has_rules=cube.has_rules,
    )


async def get_cube_rules(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    **resilience_kwargs,
) -> str | None:
    cube = await call_with_resilience(
        connection_id,
        client.cubes.get,
        cube_name,
        **resilience_kwargs,
    )

    if not cube.has_rules:
        return None

    return cube.rules.text


async def update_cube_rules(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    rules_text: str,
    **resilience_kwargs,
) -> None:
    # Writes are single-attempt: never blindly re-fire a failed write.
    await call_with_resilience(
        connection_id,
        client.cubes.update_or_create_rules,
        cube_name,
        rules_text,
        max_retries=0,
        **resilience_kwargs,
    )


async def check_cube_rules(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    **resilience_kwargs,
) -> list:
    """Server-side syntax check of the cube's PERSISTED rules (error list —
    empty = valid). There is no dry-run for rules in TM1: validation happens
    after apply, which is why the change pipeline snapshots first.

    None when the server has no rule check (TM1 11.0). Such a server
    refuses invalid rule syntax when the rules are saved, so a save that
    succeeded is the check that was available."""

    def check():
        try:
            return client.cubes.check_rules(cube_name)
        except Exception as exc:
            if compat.is_unsupported_action(exc, "CheckRules"):
                return None
            raise

    check.__name__ = "check_rules"
    return await call_with_resilience(connection_id, check, **resilience_kwargs)


async def list_cubes_with_rules(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> list[str]:
    """Names of cubes that carry a rule, so an audit can skip the rest."""

    return await call_with_resilience(
        connection_id,
        client.cubes.get_all_names_with_rules,
        skip_control_cubes=True,
        **resilience_kwargs,
    ) or []


async def search_rule_substring(
    client: TM1Service,
    connection_id: uuid.UUID,
    substring: str,
    **resilience_kwargs,
) -> list[str]:
    """Cubes whose rule text contains substring. Matched on the server."""

    cubes = await call_with_resilience(
        connection_id,
        client.cubes.search_for_rule_substring,
        substring=substring,
        skip_control_cubes=True,
        case_insensitive=True,
        space_insensitive=True,
        **resilience_kwargs,
    )
    return [cube.name for cube in (cubes or [])]
