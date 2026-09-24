"""Model structure TM1py does not surface through cube/dimension services.

Views, subsets, attributes, hierarchies and server state. These are the
ordinary questions a developer asks that PA-Copilot previously could not
answer at all - "what does this view select", "which aliases exist on this
dimension", "what sits under this consolidation".

Everything here is read-only and row-capped. A dimension with a million
elements must not be able to turn one tool call into a context overflow.
"""

import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

MAX_ITEMS = 200


def cap(items: list, limit: int = MAX_ITEMS) -> tuple[list, bool]:
    """Return (items, truncated). Callers must report the truncation."""

    if len(items) <= limit:
        return items, False
    return items[:limit], True


async def list_views(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    **resilience_kwargs,
) -> dict:
    public, private = await call_with_resilience(
        connection_id,
        client.views.get_all_names,
        cube_name=cube_name,
        **resilience_kwargs,
    )
    return {"public": list(public or []), "private": list(private or [])}


async def list_hierarchies(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.hierarchies.get_all_names,
        dimension_name=dimension_name,
        **resilience_kwargs,
    ) or []


async def get_default_member(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str,
    **resilience_kwargs,
) -> str | None:
    return await call_with_resilience(
        connection_id,
        client.hierarchies.get_default_member,
        dimension_name=dimension_name,
        hierarchy_name=hierarchy_name,
        **resilience_kwargs,
    )


async def list_subsets(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.subsets.get_all_names,
        dimension_name=dimension_name,
        hierarchy_name=hierarchy_name,
        private=False,
        **resilience_kwargs,
    ) or []


async def get_attribute_definitions(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str,
    **resilience_kwargs,
) -> list[dict]:
    attributes = await call_with_resilience(
        connection_id,
        client.elements.get_element_attributes,
        dimension_name=dimension_name,
        hierarchy_name=hierarchy_name,
        **resilience_kwargs,
    )
    return [
        {"name": a.name, "type": str(getattr(a, "attribute_type", "") or "")}
        for a in (attributes or [])
    ]


async def get_parents(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str,
    element_name: str,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.elements.get_parents,
        dimension_name=dimension_name,
        hierarchy_name=hierarchy_name,
        element_name=element_name,
        **resilience_kwargs,
    ) or []


async def get_leaves_under(
    client: TM1Service,
    connection_id: uuid.UUID,
    dimension_name: str,
    hierarchy_name: str,
    consolidation: str,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.elements.get_leaves_under_consolidation,
        dimension_name=dimension_name,
        hierarchy_name=hierarchy_name,
        consolidation=consolidation,
        **resilience_kwargs,
    ) or []


async def get_server_state(
    client: TM1Service,
    connection_id: uuid.UUID,
    **resilience_kwargs,
) -> dict:
    """Version, active sessions and running threads.

    Each part is fetched independently: monitoring endpoints are the first
    thing a locked-down TM1 install blocks, and losing the version because
    the session list was refused would be a poor trade.
    """

    state: dict = {}

    async def attempt(key: str, fn, **kwargs):
        try:
            state[key] = await call_with_resilience(
                connection_id, fn, **kwargs, **resilience_kwargs
            )
        except Exception as exc:  # noqa: BLE001
            state[key] = None
            state.setdefault("unavailable", {})[key] = type(exc).__name__

    await attempt("version", client.server.get_product_version)
    await attempt("sessions", client.monitoring.get_sessions, include_threads=False)
    await attempt("threads", client.monitoring.get_active_threads)

    sessions = state.get("sessions") or []
    threads = state.get("threads") or []

    return {
        "version": state.get("version"),
        "session_count": len(sessions),
        "active_thread_count": len(threads),
        "threads": [
            {
                "id": t.get("ID"),
                "name": t.get("Name"),
                "state": t.get("State"),
                "function": t.get("Function"),
                "object_name": t.get("ObjectName"),
            }
            for t in (threads[:25] if isinstance(threads, list) else [])
            if isinstance(t, dict)
        ],
        "unavailable": state.get("unavailable") or {},
    }
