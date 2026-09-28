"""TM1 gateways: managed by admins, called by the gateway program.

Two audiences, two routers:

* `/tm1/gateways` — people in the app create, list, re-key and remove
  gateways (tm1.read to list, tm1.write to change).
* `/gateway/*` — the gateway program itself, authenticated by its key:
  it waits for TM1 requests (`/gateway/poll`) and sends back what TM1
  answered (`/gateway/answer`). See src/tm1/gateway/relay.py.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.core import rate_limit
from src.core.exceptions import AuthenticationException
from src.core.logging import app_logger
from src.database.models.tm1_connection import TM1Connection
from src.database.models.tm1_gateway import TM1Gateway
from src.database.session import get_db
from src.schemas.response import ApiResponse
from src.schemas.auth import UserResponse
from src.schemas.tm1_gateway import (
    GatewayAnswerPart,
    GatewayCreate,
    GatewayKeyResponse,
    GatewayPollRequest,
    GatewayResponse,
)
from src.tm1.gateway.relay import get_broker
from src.tm1.gateway.service import is_online, tm1_gateway_service

admin_router = APIRouter(prefix="/tm1/gateways", tags=["TM1 Gateways"])
agent_router = APIRouter(prefix="/gateway", tags=["TM1 Gateway (agent)"])

# Wrong keys allowed per address per auth window before 429.
_BAD_KEYS_PER_WINDOW = 20


async def _connection_counts(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    rows = await db.execute(
        select(TM1Connection.gateway_id, func.count())
        .where(
            TM1Connection.organization_id == organization_id,
            TM1Connection.gateway_id.is_not(None),
        )
        .group_by(TM1Connection.gateway_id)
    )
    return {gateway_id: count for gateway_id, count in rows.all()}


def _describe(gateway: TM1Gateway, counts: dict) -> GatewayResponse:
    return GatewayResponse(
        id=gateway.id,
        name=gateway.name,
        online=is_online(gateway),
        last_seen_at=gateway.last_seen_at,
        version=gateway.version,
        hostname=gateway.hostname,
        created_at=gateway.created_at,
        connection_count=counts.get(gateway.id, 0),
    )


def _server_url(request: Request) -> str:
    # The address the gateway should call: this API, as the browser reached it.
    return str(request.base_url).rstrip("/")


# ------------------------------------------------------------------ admins


@admin_router.get("", response_model=ApiResponse[list[GatewayResponse]])
async def list_gateways(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    gateways = await tm1_gateway_service.list(db, current_user.organization_id)
    counts = await _connection_counts(db, current_user.organization_id)
    return ApiResponse(success=True, data=[_describe(g, counts) for g in gateways])


@admin_router.post("", response_model=ApiResponse[GatewayKeyResponse])
async def create_gateway(
    body: GatewayCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    gateway, key = await tm1_gateway_service.create(
        db,
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        name=body.name,
    )
    await db.refresh(gateway)
    app_logger.info(f"tm1_gateway_created id={gateway.id} by={current_user.id}")
    return ApiResponse(
        success=True,
        data=GatewayKeyResponse(
            gateway=_describe(gateway, {}), key=key, server_url=_server_url(request)
        ),
    )


@admin_router.post("/{gateway_id}/rotate-key", response_model=ApiResponse[GatewayKeyResponse])
async def rotate_gateway_key(
    gateway_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    gateway, key = await tm1_gateway_service.rotate_key(
        db, gateway_id, current_user.organization_id
    )
    counts = await _connection_counts(db, current_user.organization_id)
    app_logger.info(f"tm1_gateway_key_rotated id={gateway.id} by={current_user.id}")
    return ApiResponse(
        success=True,
        data=GatewayKeyResponse(
            gateway=_describe(gateway, counts), key=key, server_url=_server_url(request)
        ),
    )


@admin_router.delete("/{gateway_id}", response_model=ApiResponse[dict])
async def delete_gateway(
    gateway_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    await tm1_gateway_service.delete(db, gateway_id, current_user.organization_id)
    app_logger.info(f"tm1_gateway_deleted id={gateway_id} by={current_user.id}")
    return ApiResponse(success=True, data={"deleted": True})


# ---------------------------------------------------------- the gateway


async def current_gateway(
    request: Request, db: AsyncSession = Depends(get_db)
) -> TM1Gateway:
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header.lower().startswith("bearer ") else ""
    try:
        return await tm1_gateway_service.authenticate(db, key)
    except AuthenticationException:
        # Only failures count: a working gateway polls constantly.
        await rate_limit.enforce_ip(
            scope="gateway_key",
            client_ip=rate_limit.client_ip_of(request),
            limit=_BAD_KEYS_PER_WINDOW,
        )
        raise


@agent_router.post("/poll")
async def poll(
    body: GatewayPollRequest,
    db: AsyncSession = Depends(get_db),
    gateway: TM1Gateway = Depends(current_gateway),
):
    """Wait up to `wait` seconds for a TM1 request for this gateway."""

    await tm1_gateway_service.mark_seen(
        db, gateway, version=body.version, hostname=body.hostname
    )
    gateway_id = str(gateway.id)
    # Commit before waiting: a long poll must not hold a database
    # connection for its whole duration.
    await db.commit()

    message = await asyncio.to_thread(get_broker().pop_request, gateway_id, body.wait)
    if message is None:
        return Response(status_code=204)
    return {"request": message}


@agent_router.post("/answer", response_model=ApiResponse[dict])
async def answer(
    part: GatewayAnswerPart,
    gateway: TM1Gateway = Depends(current_gateway),
):
    """One part of what TM1 answered (or why it could not be asked)."""

    payload = part.model_dump(exclude_none=True)
    await asyncio.to_thread(get_broker().push_answer_part, part.id, payload)
    return ApiResponse(success=True, data={"received": part.index})

