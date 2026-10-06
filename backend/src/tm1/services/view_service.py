"""Public MDX views, for the governed `create_view` change.

Reading a view's definition lives in structure_service.get_view. The
writes here are only ever reached from change_service for an approved
`create_view` change, its verification, or its rollback. Every view is
public: a private view belongs to whoever's session created it, which
here would be the service account, so no one could open it.
"""

import uuid

from TM1py import TM1Service
from TM1py.Objects import MDXView

from src.tm1.resilience import call_with_resilience


async def view_exists(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    view_name: str,
    **resilience_kwargs,
) -> bool:
    return bool(
        await call_with_resilience(
            connection_id,
            client.views.exists,
            cube_name=cube_name,
            view_name=view_name,
            private=False,
            **resilience_kwargs,
        )
    )


async def create_mdx_view(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    view_name: str,
    mdx: str,
    **resilience_kwargs,
) -> None:
    # Writes are single-attempt: never blindly re-fire a failed write.
    await call_with_resilience(
        connection_id,
        client.views.create,
        MDXView(cube_name, view_name, mdx),
        private=False,
        max_retries=0,
        **resilience_kwargs,
    )


async def delete_view(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube_name: str,
    view_name: str,
    **resilience_kwargs,
) -> None:
    await call_with_resilience(
        connection_id,
        client.views.delete,
        cube_name=cube_name,
        view_name=view_name,
        private=False,
        max_retries=0,
        **resilience_kwargs,
    )
