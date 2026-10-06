"""The platform owner's view across every workspace (Super Admin only).

Who has an account, who signed in and from where, which TM1 servers each
organization connected and with which TM1 user, who used those connections
and on what — and the levers to stop misuse: deactivate a person, end their
sessions, or suspend a connection.

What it never shows: a password, API key or any other secret. Connection
rows are built field by field below, so a column added to TM1Connection
later cannot leak into this view by accident.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.signups import _every_organization, require_super_admin
from src.core.exceptions import NotFoundException, ValidationException
from src.core.rate_limit import client_ip_of
from src.database.models.ai_tool_execution import AIToolExecution
from src.database.models.ai_usage import AIUsage
from src.database.models.audit_log import AuditLog
from src.database.models.organization import Organization
from src.database.models.request_log import RequestLog
from src.database.models.sign_in_event import SignInEvent
from src.database.models.tm1_connection import TM1Connection
from src.database.models.tm1_gateway import TM1Gateway
from src.database.models.user import User
from src.database.session import get_db
from src.repositories.user_role_repository import user_role_repository
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.audit_service import audit_service
from src.services.token_revocation_service import token_revocation_service
from src.tm1.client.connection_manager import tm1_connection_manager

router = APIRouter(prefix="/admin/platform", tags=["Platform"])

USAGE_DAYS = 30
MAX_ROWS = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _person(user: User | None) -> dict | None:
    if user is None:
        return None
    return {"id": str(user.id), "name": f"{user.first_name} {user.last_name}".strip(), "email": user.email}


def _brief(arguments: dict | None) -> dict:
    """A tool call's arguments, minus the connection id (shown separately)
    and cut short: enough to see which cube or process was touched."""

    out = {}
    for key, value in (arguments or {}).items():
        if key == "connection_id":
            continue
        text = value if isinstance(value, str) else repr(value)
        out[key] = text if len(text) <= 200 else f"{text[:200]}…"
    return out


async def _users_by_id(db: AsyncSession, ids) -> dict[uuid.UUID, User]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()}


async def _connection_use(db: AsyncSession, since: datetime) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:
    """(connection, user, last used) for every use since `since`: TM1 calls
    made through the API, and tool calls the assistant made for someone."""

    connection_text = AIToolExecution.arguments["connection_id"].astext
    by_tools = (await db.execute(
        select(connection_text, AIToolExecution.user_id, func.max(AIToolExecution.created_at))
        .where(AIToolExecution.created_at >= since, connection_text.is_not(None))
        .group_by(connection_text, AIToolExecution.user_id)
    )).all()
    by_api = (await db.execute(
        select(AuditLog.entity_id, AuditLog.user_id, func.max(AuditLog.created_at))
        .where(AuditLog.created_at >= since, AuditLog.entity == "TM1Connection",
               AuditLog.entity_id.is_not(None), AuditLog.user_id.is_not(None),
               # Suspending or resuming one is not using it.
               ~AuditLog.action.startswith("platform_", autoescape=True))
        .group_by(AuditLog.entity_id, AuditLog.user_id)
    )).all()

    uses = []
    for connection, user, at in [*by_tools, *by_api]:
        try:
            uses.append((uuid.UUID(str(connection)), user, at))
        except ValueError:
            continue
    return uses


@router.get("/overview", response_model=ApiResponse[dict])
async def overview(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
):
    day = _now() - timedelta(days=1)
    with _every_organization(db):
        count = lambda stmt: db.scalar(stmt)  # noqa: E731
        data = {
            "organizations": await count(select(func.count(Organization.id))),
            "users": await count(select(func.count(User.id))),
            "active_users_24h": await count(select(func.count(User.id)).where(User.last_seen_at >= day)),
            "pending_signups": await count(select(func.count(User.id)).where(User.registration_status == "pending")),
            "sign_ins_24h": await count(select(func.count(SignInEvent.id)).where(
                SignInEvent.created_at >= day, SignInEvent.success.is_(True))),
            "failed_sign_ins_24h": await count(select(func.count(SignInEvent.id)).where(
                SignInEvent.created_at >= day, SignInEvent.success.is_(False))),
            "connections": await count(select(func.count(TM1Connection.id))),
            "suspended_connections": await count(select(func.count(TM1Connection.id)).where(
                TM1Connection.suspended_at.is_not(None))),
            "api_requests_24h": await count(select(func.count(RequestLog.id)).where(RequestLog.created_at >= day)),
            "failed_api_requests_24h": await count(select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= day, RequestLog.status_code >= 400)),
            "ai_requests_24h": await count(select(func.count(AIUsage.id)).where(AIUsage.created_at >= day)),
            "ai_cost_24h": float(await count(select(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0))
                                             .where(AIUsage.created_at >= day)) or 0),
        }
    return ApiResponse(success=True, data=data)


@router.get("/users", response_model=ApiResponse[list[dict]])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
):
    since = _now() - timedelta(days=USAGE_DAYS)
    with _every_organization(db):
        rows = (await db.execute(
            select(User, Organization.name).join(Organization, Organization.id == User.organization_id)
            .order_by(User.last_seen_at.desc().nulls_last(), User.created_at.desc()).limit(MAX_ROWS)
        )).all()
        ids = [user.id for user, _ in rows]
        roles = await user_role_repository.role_names_by_user(db, ids)

        owned = dict((await db.execute(
            select(TM1Connection.created_by, func.count(TM1Connection.id)).group_by(TM1Connection.created_by)
        )).all())
        ai = {u: (n, float(c)) for u, n, c in (await db.execute(
            select(AIUsage.user_id, func.count(AIUsage.id), func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0))
            .where(AIUsage.created_at >= since).group_by(AIUsage.user_id)
        )).all()}
        used: dict[uuid.UUID, set] = {}
        for connection, user, _at in await _connection_use(db, since):
            used.setdefault(user, set()).add(connection)

        # The address each person last signed in from.
        last_ip = {}
        for user_id, ip in (await db.execute(
            select(SignInEvent.user_id, SignInEvent.ip_address)
            .where(SignInEvent.success.is_(True), SignInEvent.user_id.in_(ids))
            .order_by(SignInEvent.user_id, SignInEvent.created_at.desc())
            .distinct(SignInEvent.user_id)
        )).all():
            last_ip[user_id] = ip

    return ApiResponse(success=True, data=[
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "name": f"{user.first_name} {user.last_name}".strip(),
            "organization_id": str(user.organization_id),
            "organization": organization,
            "roles": roles.get(user.id, []),
            "registration_status": user.registration_status,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
            "last_seen_at": user.last_seen_at,
            "last_ip": last_ip.get(user.id),
            "connections_owned": owned.get(user.id, 0),
            "connections_used_30d": len(used.get(user.id, ())),
            "ai_requests_30d": ai.get(user.id, (0, 0.0))[0],
            "ai_cost_30d": round(ai.get(user.id, (0, 0.0))[1], 4),
        }
        for user, organization in rows
    ])


@router.get("/connections", response_model=ApiResponse[list[dict]])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
):
    since = _now() - timedelta(days=USAGE_DAYS)
    with _every_organization(db):
        rows = (await db.execute(
            select(TM1Connection, Organization.name, TM1Gateway.name)
            .join(Organization, Organization.id == TM1Connection.organization_id)
            .outerjoin(TM1Gateway, TM1Gateway.id == TM1Connection.gateway_id)
            .order_by(Organization.name, TM1Connection.name).limit(MAX_ROWS)
        )).all()

        users_of: dict[uuid.UUID, set] = {}
        last_used: dict[uuid.UUID, datetime] = {}
        for connection, user, at in await _connection_use(db, since):
            users_of.setdefault(connection, set()).add(user)
            if connection not in last_used or at > last_used[connection]:
                last_used[connection] = at
        people = await _users_by_id(
            db, {c.created_by for c, *_ in rows} | {c.suspended_by for c, *_ in rows}
            | {u for s in users_of.values() for u in s}
        )

    return ApiResponse(success=True, data=[
        {
            "id": str(c.id),
            "organization_id": str(c.organization_id),
            "organization": organization,
            "name": c.name,
            "address": c.address,
            "port": c.port,
            "ssl": c.ssl,
            "authentication_type": c.authentication_type,
            # The TM1 login name, never its password or API key.
            "tm1_user": c.username,
            "tenant": c.tenant,
            "database": c.database,
            "environment": c.environment,
            "visibility": c.visibility,
            "is_active": c.is_active,
            "gateway": gateway,
            "owner": _person(people.get(c.created_by)),
            "created_at": c.created_at,
            "last_used_at": last_used.get(c.id),
            "used_by_30d": [p for p in (_person(people.get(u)) for u in users_of.get(c.id, ())) if p],
            "suspended_at": c.suspended_at,
            "suspended_reason": c.suspended_reason,
            "suspended_by": _person(people.get(c.suspended_by)),
        }
        for c, organization, gateway in rows
    ])


@router.get("/users/{user_id}/activity", response_model=ApiResponse[dict])
async def user_activity(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
    days: int = Query(default=30, ge=1, le=365),
):
    since = _now() - timedelta(days=days)
    with _every_organization(db):
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundException("User not found.")

        audits = (await db.execute(
            select(AuditLog).where(AuditLog.user_id == user_id, AuditLog.created_at >= since)
            .order_by(AuditLog.created_at.desc()).limit(MAX_ROWS)
        )).scalars().all()
        tools = (await db.execute(
            select(AIToolExecution).where(AIToolExecution.user_id == user_id, AIToolExecution.created_at >= since)
            .order_by(AIToolExecution.created_at.desc()).limit(MAX_ROWS)
        )).scalars().all()
        requests = (await db.execute(
            select(RequestLog).where(RequestLog.user_id == user_id, RequestLog.created_at >= since)
            .order_by(RequestLog.created_at.desc()).limit(MAX_ROWS)
        )).scalars().all()
        sign_ins = (await db.execute(
            select(SignInEvent).where(
                or_(SignInEvent.user_id == user_id, SignInEvent.identifier.in_((user.email, user.username))),
                SignInEvent.created_at >= since,
            ).order_by(SignInEvent.created_at.desc()).limit(100)
        )).scalars().all()

        connection_ids = {a.entity_id for a in audits if a.entity == "TM1Connection" and a.entity_id}
        connection_ids |= {r.connection_id for r in requests if r.connection_id}
        for t in tools:
            try:
                connection_ids.add(uuid.UUID(str((t.arguments or {}).get("connection_id"))))
            except ValueError:
                pass
        names = dict((await db.execute(
            select(TM1Connection.id, TM1Connection.name).where(TM1Connection.id.in_(connection_ids))
        )).all()) if connection_ids else {}

    def connection_of(value) -> dict | None:
        try:
            cid = uuid.UUID(str(value))
        except ValueError:
            return None
        return {"id": str(cid), "name": names.get(cid, "(deleted connection)")}

    events = [
        {
            "kind": "action",
            "at": a.created_at,
            "action": a.action,
            "entity": a.entity,
            "connection": connection_of(a.entity_id) if a.entity == "TM1Connection" else None,
            "details": _brief(a.new_values),
            "ip_address": a.ip_address,
        }
        for a in audits
    ] + [
        {
            "kind": "tool",
            "at": t.created_at,
            "action": t.tool_name,
            "entity": t.agent or "assistant",
            "connection": connection_of((t.arguments or {}).get("connection_id")),
            "details": _brief(t.arguments),
            "status": t.status,
        }
        for t in tools
    ]
    events.sort(key=lambda e: e["at"], reverse=True)

    return ApiResponse(success=True, data={
        "user": {**_person(user), "is_active": user.is_active},
        "days": days,
        "events": events[:MAX_ROWS],
        "requests": [
            {**_request_row(r), "connection": connection_of(r.connection_id) if r.connection_id else None}
            for r in requests
        ],
        "sign_ins": [_sign_in_row(s) for s in sign_ins],
    })


def _request_row(r: RequestLog, user: User | None = None, organization: str | None = None) -> dict:
    return {
        "id": str(r.id),
        "at": r.created_at,
        "method": r.method,
        "path": r.path,
        "route": r.route,
        "status_code": r.status_code,
        "duration_ms": r.duration_ms,
        "ip_address": r.ip_address,
        "user_agent": r.user_agent,
        "user": _person(user),
        "organization": organization,
    }


@router.get("/requests", response_model=ApiResponse[list[dict]])
async def list_requests(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
    user_id: uuid.UUID | None = None,
    method: str | None = Query(default=None, pattern="^(GET|POST|PUT|PATCH|DELETE)$"),
    failed_only: bool = False,
    path: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=300, ge=1, le=MAX_ROWS),
):
    """Every API request people made, newest first."""

    with _every_organization(db):
        stmt = (
            select(RequestLog, User, Organization.name)
            .outerjoin(User, User.id == RequestLog.user_id)
            .outerjoin(Organization, Organization.id == User.organization_id)
            .order_by(RequestLog.created_at.desc()).limit(limit)
        )
        if user_id:
            stmt = stmt.where(RequestLog.user_id == user_id)
        if method:
            stmt = stmt.where(RequestLog.method == method)
        if failed_only:
            stmt = stmt.where(RequestLog.status_code >= 400)
        if path:
            stmt = stmt.where(RequestLog.path.contains(path, autoescape=True))
        rows = (await db.execute(stmt)).all()
    return ApiResponse(success=True, data=[_request_row(r, u, o) for r, u, o in rows])


def _sign_in_row(s: SignInEvent, user: User | None = None, organization: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "at": s.created_at,
        "method": s.method,
        "success": s.success,
        "identifier": s.identifier,
        "reason": s.reason,
        "ip_address": s.ip_address,
        "user_agent": s.user_agent,
        "user": _person(user),
        "organization": organization,
    }


@router.get("/sign-ins", response_model=ApiResponse[list[dict]])
async def list_sign_ins(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
    success: bool | None = None,
    limit: int = Query(default=200, ge=1, le=MAX_ROWS),
):
    with _every_organization(db):
        stmt = (
            select(SignInEvent, User, Organization.name)
            .outerjoin(User, User.id == SignInEvent.user_id)
            .outerjoin(Organization, Organization.id == SignInEvent.organization_id)
            .order_by(SignInEvent.created_at.desc()).limit(limit)
        )
        if success is not None:
            stmt = stmt.where(SignInEvent.success.is_(success))
        rows = (await db.execute(stmt)).all()
    return ApiResponse(success=True, data=[_sign_in_row(s, u, o) for s, u, o in rows])


@router.get("/audit", response_model=ApiResponse[list[dict]])
async def list_audit(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=200, ge=1, le=MAX_ROWS),
):
    with _every_organization(db):
        stmt = (
            select(AuditLog, User, Organization.name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .outerjoin(Organization, Organization.id == AuditLog.organization_id)
            .order_by(AuditLog.created_at.desc()).limit(limit)
        )
        if organization_id:
            stmt = stmt.where(AuditLog.organization_id == organization_id)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        rows = (await db.execute(stmt)).all()

        connection_ids = {a.entity_id for a, *_ in rows if a.entity == "TM1Connection" and a.entity_id}
        names = dict((await db.execute(
            select(TM1Connection.id, TM1Connection.name).where(TM1Connection.id.in_(connection_ids))
        )).all()) if connection_ids else {}

    return ApiResponse(success=True, data=[
        {
            "id": str(a.id),
            "at": a.created_at,
            "action": a.action,
            "entity": a.entity,
            "entity_id": str(a.entity_id) if a.entity_id else None,
            "connection": names.get(a.entity_id) if a.entity == "TM1Connection" else None,
            "user": _person(u),
            "organization": organization,
            "details": _brief(a.new_values),
            "ip_address": a.ip_address,
            "user_agent": a.user_agent,
        }
        for a, u, organization in rows
    ])


# ---------------------------------------------------------------- actions


class Reason(BaseModel):
    reason: str = Field(default="", max_length=500)


async def _audit(db, request: Request, caller: UserResponse, action: str, entity: str,
                 entity_id: uuid.UUID, organization_id: uuid.UUID, reason: str = "") -> None:
    await audit_service.log(
        db,
        organization_id=organization_id,
        user_id=caller.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        new_values={"reason": reason, "by": "platform_admin"} if reason else {"by": "platform_admin"},
        ip_address=client_ip_of(request),
        user_agent=request.headers.get("user-agent"),
    )


async def _target_user(db: AsyncSession, user_id: uuid.UUID, caller: UserResponse) -> User:
    if user_id == caller.id:
        raise ValidationException("You cannot restrict your own account.")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundException("User not found.")
    return user


@router.post("/users/{user_id}/deactivate", response_model=ApiResponse[dict])
async def deactivate_user(
    user_id: uuid.UUID,
    body: Reason,
    request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    """Block sign-in and every request at once, and end all sessions."""

    with _every_organization(db):
        user = await _target_user(db, user_id, caller)
        user.is_active = False
        await token_revocation_service.revoke_all_for_user(db, user.id)
    await _audit(db, request, caller, "platform_deactivate_user", "User", user.id, user.organization_id, body.reason)
    return ApiResponse(success=True, data={"id": str(user.id), "is_active": False})


@router.post("/users/{user_id}/activate", response_model=ApiResponse[dict])
async def activate_user(
    user_id: uuid.UUID,
    body: Reason,
    request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    with _every_organization(db):
        user = await _target_user(db, user_id, caller)
        user.is_active = True
        await db.flush()
    await _audit(db, request, caller, "platform_activate_user", "User", user.id, user.organization_id, body.reason)
    return ApiResponse(success=True, data={"id": str(user.id), "is_active": True})


@router.post("/users/{user_id}/sign-out", response_model=ApiResponse[dict])
async def sign_out_user(
    user_id: uuid.UUID,
    body: Reason,
    request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    """End every session; the person can sign in again."""

    with _every_organization(db):
        user = await _target_user(db, user_id, caller)
        await token_revocation_service.revoke_all_for_user(db, user.id)
    await _audit(db, request, caller, "platform_sign_out_user", "User", user.id, user.organization_id, body.reason)
    return ApiResponse(success=True, data={"id": str(user.id)})


async def _target_connection(db: AsyncSession, connection_id: uuid.UUID) -> TM1Connection:
    connection = (await db.execute(
        select(TM1Connection).where(TM1Connection.id == connection_id)
    )).scalar_one_or_none()
    if connection is None:
        raise NotFoundException("TM1 connection not found.")
    return connection


@router.post("/connections/{connection_id}/suspend", response_model=ApiResponse[dict])
async def suspend_connection(
    connection_id: uuid.UUID,
    body: Reason,
    request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    """Stop every use of this connection's credentials until resumed."""

    with _every_organization(db):
        connection = await _target_connection(db, connection_id)
        connection.suspended_at = _now()
        connection.suspended_reason = body.reason or None
        connection.suspended_by = caller.id
        await db.flush()
    tm1_connection_manager.invalidate(connection.id)
    await _audit(db, request, caller, "platform_suspend_connection", "TM1Connection", connection.id,
                 connection.organization_id, body.reason)
    return ApiResponse(success=True, data={"id": str(connection.id), "suspended": True})


@router.post("/connections/{connection_id}/resume", response_model=ApiResponse[dict])
async def resume_connection(
    connection_id: uuid.UUID,
    body: Reason,
    request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    with _every_organization(db):
        connection = await _target_connection(db, connection_id)
        connection.suspended_at = None
        connection.suspended_reason = None
        connection.suspended_by = None
        await db.flush()
    await _audit(db, request, caller, "platform_resume_connection", "TM1Connection", connection.id,
                 connection.organization_id, body.reason)
    return ApiResponse(success=True, data={"id": str(connection.id), "suspended": False})
