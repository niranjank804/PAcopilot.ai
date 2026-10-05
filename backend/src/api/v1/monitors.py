"""Monitoring rules and alerts.

Making a rule needs tm1.read and use of its connection (security rules
also tm1.security.read); changing or deleting one is for the person who
made it or an admin. Alerts are seen and acknowledged by anyone who may
use the connection and has monitoring.view.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.core.config import settings
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.monitoring_rules_service import KINDS, monitoring_rules_service

router = APIRouter(prefix="/monitoring", tags=["Monitoring rules"])

Kind = Literal[tuple(KINDS)]  # type: ignore[valid-type]


class RuleCreate(BaseModel):
    connection_id: uuid.UUID
    kind: Kind
    params: dict = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=255)
    interval_minutes: int = Field(default=15, ge=15, le=1440)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    params: dict | None = None
    status: Literal["active", "paused"] | None = None
    interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    notify: list[uuid.UUID] | None = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    name: str
    kind: str
    params: dict
    status: str
    source: str
    rationale: str | None
    interval_minutes: int
    notify: list
    last_checked_at: datetime | None
    last_error: str | None
    consecutive_errors: int
    created_by: uuid.UUID
    created_at: datetime


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    connection_id: uuid.UUID
    severity: str
    title: str
    detail: str | None
    evidence: dict | None
    fired_at: datetime
    status: str
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    emailed: bool


class KindInfo(BaseModel):
    kind: str
    label: str


class MonitoringSetup(BaseModel):
    kinds: list[KindInfo]
    email_configured: bool
    schedule_path: str


@router.get("/setup", response_model=ApiResponse[MonitoringSetup])
async def monitoring_setup(current_user: UserResponse = Depends(require_permission("monitoring.view"))):
    """What can be watched, and whether alerts can be emailed."""

    return ApiResponse(success=True, data=MonitoringSetup(
        kinds=[KindInfo(kind=k, label=v) for k, v in KINDS.items()],
        email_configured=bool(settings.SMTP_HOST),
        schedule_path="/internal/cron/monitors",
    ))


@router.get("/rules", response_model=ApiResponse[list[RuleResponse]])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
    connection_id: uuid.UUID | None = Query(default=None),
):
    rules = await monitoring_rules_service.list_rules(db, current_user.organization_id, current_user.id, connection_id)
    return ApiResponse(success=True, data=[RuleResponse.model_validate(r) for r in rules])


@router.post("/rules", response_model=ApiResponse[RuleResponse], status_code=201)
async def create_rule(
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    rule = await monitoring_rules_service.create(
        db, organization_id=current_user.organization_id, user_id=current_user.id,
        connection_id=body.connection_id, kind=body.kind, params=body.params, name=body.name,
        interval_minutes=body.interval_minutes,
    )
    return ApiResponse(success=True, data=RuleResponse.model_validate(rule))


@router.patch("/rules/{rule_id}", response_model=ApiResponse[RuleResponse])
async def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    rule = await monitoring_rules_service.get(db, rule_id, current_user.organization_id, current_user.id)
    rule = await monitoring_rules_service.update(db, rule, current_user.id, body.model_dump(exclude_unset=True))
    return ApiResponse(success=True, data=RuleResponse.model_validate(rule))


@router.delete("/rules/{rule_id}", response_model=ApiResponse[None])
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    rule = await monitoring_rules_service.get(db, rule_id, current_user.organization_id, current_user.id)
    await monitoring_rules_service.delete(db, rule, current_user.id)
    return ApiResponse(success=True, data=None)


@router.post("/rules/{rule_id}/check", response_model=ApiResponse[list[AlertResponse]])
async def check_rule_now(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    """Check now. Returns the alerts this check newly raised (a first check
    only records the baseline)."""

    rule = await monitoring_rules_service.get(db, rule_id, current_user.organization_id, current_user.id)
    raised = await monitoring_rules_service.check_now(db, rule, current_user.id)
    return ApiResponse(success=True, data=[AlertResponse.model_validate(a) for a in raised])


@router.get("/alerts", response_model=ApiResponse[list[AlertResponse]])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
    status: Literal["open", "acknowledged", "resolved"] | None = Query(default=None),
    connection_id: uuid.UUID | None = Query(default=None),
):
    alerts = await monitoring_rules_service.list_alerts(
        db, current_user.organization_id, current_user.id, status=status, connection_id=connection_id
    )
    return ApiResponse(success=True, data=[AlertResponse.model_validate(a) for a in alerts])


@router.get("/alerts/open-count", response_model=ApiResponse[dict])
async def open_alert_count(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
):
    alerts = await monitoring_rules_service.list_alerts(
        db, current_user.organization_id, current_user.id, status="open", limit=100
    )
    return ApiResponse(success=True, data={
        "open": len(alerts),
        "critical": sum(1 for a in alerts if a.severity == "critical"),
    })


@router.post("/alerts/{alert_id}/{action}", response_model=ApiResponse[AlertResponse])
async def change_alert(
    alert_id: uuid.UUID,
    action: Literal["acknowledge", "resolve"],
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
):
    alert = await monitoring_rules_service.set_alert_status(
        db, alert_id, current_user.organization_id, current_user.id,
        "acknowledged" if action == "acknowledge" else "resolved",
    )
    return ApiResponse(success=True, data=AlertResponse.model_validate(alert))



