"""Team workspace: work items, shared conversations, and what the team is doing.

Everything here is read through the same access rules as the rest of the
API: a shared conversation is readable by the organization, a private one
only by its owner; a TM1 change, a health scan or a connection's activity
only by people who may use that connection. A work item never widens that.

Reading and writing work items needs ai.chat, the permission every role
has: tracking work is for the whole team, and every edit is audited.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.models.ai_conversation import AIConversation
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_health import TM1HealthScan
from src.database.session import get_db
from src.schemas.ai import SharedConversationSummary
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.work_item_service import user_names, work_item_service
from src.tm1.service import tm1_integration_service

router = APIRouter(prefix="/team", tags=["Team workspace"])

Status = Literal["open", "in_progress", "resolved", "closed"]


class WorkItemCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class WorkItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    status: Status | None = None
    root_cause: str | None = Field(default=None, max_length=10_000)
    resolution: str | None = Field(default=None, max_length=10_000)


class LinkCreate(BaseModel):
    kind: Literal["conversation", "change"]
    target_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2000)


class WorkItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    title: str
    description: str | None
    status: str
    root_cause: str | None
    resolution: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TimelineEvent(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: str | None = None
    actor: str | None = None
    link_id: uuid.UUID | None = None


class LinkedRecord(BaseModel):
    link_id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    available: bool
    title: str
    note: str | None = None
    linked_at: datetime
    linked_by_name: str | None = None
    # Conversations
    owner_name: str | None = None
    messages: int | None = None
    # Changes
    status: str | None = None
    connection_id: uuid.UUID | None = None
    connection_name: str | None = None
    environment: str | None = None


class ProgressStep(BaseModel):
    key: str
    label: str
    done: bool


class WorkItemDetail(BaseModel):
    item: WorkItemResponse
    created_by_name: str | None
    progress: list[ProgressStep]
    links: list[LinkedRecord]
    events: list[TimelineEvent]


async def _detail(db, item, user_id) -> WorkItemDetail:
    timeline = await work_item_service.timeline(db, item, user_id)
    return WorkItemDetail(
        item=WorkItemResponse.model_validate(item),
        created_by_name=timeline["created_by_name"],
        progress=[ProgressStep(**p) for p in timeline["progress"]],
        links=[LinkedRecord(**{k: v for k, v in entry.items() if k in LinkedRecord.model_fields})
               for entry in timeline["links"]],
        events=[TimelineEvent(**e) for e in timeline["events"]],
    )


@router.get("/work-items", response_model=ApiResponse[list[WorkItemResponse]])
async def list_work_items(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
    status: Status | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
):
    items = await work_item_service.search(db, current_user.organization_id, status=status, query=q)
    return ApiResponse(success=True, data=[WorkItemResponse.model_validate(i) for i in items])


@router.post("/work-items", response_model=ApiResponse[WorkItemResponse], status_code=201)
async def create_work_item(
    body: WorkItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    item = await work_item_service.create(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        reference=body.reference,
        title=body.title,
        description=body.description,
    )
    return ApiResponse(success=True, data=WorkItemResponse.model_validate(item))


@router.get("/work-items/{work_item_id}", response_model=ApiResponse[WorkItemDetail])
async def get_work_item(
    work_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    item = await work_item_service.get(db, work_item_id, current_user.organization_id)
    return ApiResponse(success=True, data=await _detail(db, item, current_user.id))


@router.patch("/work-items/{work_item_id}", response_model=ApiResponse[WorkItemDetail])
async def update_work_item(
    work_item_id: uuid.UUID,
    body: WorkItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    item = await work_item_service.get(db, work_item_id, current_user.organization_id)
    await work_item_service.update(db, item, current_user.id, body.model_dump(exclude_unset=True))
    return ApiResponse(success=True, data=await _detail(db, item, current_user.id))


@router.post("/work-items/{work_item_id}/links", response_model=ApiResponse[WorkItemDetail], status_code=201)
async def link_to_work_item(
    work_item_id: uuid.UUID,
    body: LinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    item = await work_item_service.get(db, work_item_id, current_user.organization_id)
    await work_item_service.link(db, item, current_user.id, kind=body.kind, target_id=body.target_id, note=body.note)
    return ApiResponse(success=True, data=await _detail(db, item, current_user.id))


@router.delete("/work-items/{work_item_id}/links/{link_id}", response_model=ApiResponse[WorkItemDetail])
async def unlink_from_work_item(
    work_item_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    item = await work_item_service.get(db, work_item_id, current_user.organization_id)
    await work_item_service.unlink(db, item, link_id, current_user.id)
    return ApiResponse(success=True, data=await _detail(db, item, current_user.id))


@router.get("/linked-to/{target_id}", response_model=ApiResponse[list[WorkItemResponse]])
async def work_items_linked_to(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    """Which work items a conversation or change belongs to."""

    items = await work_item_service.items_linked_to(db, current_user.organization_id, target_id)
    return ApiResponse(success=True, data=[WorkItemResponse.model_validate(i) for i in items])


async def shared_conversations(db, organization_id, limit: int = 100) -> list[SharedConversationSummary]:
    result = await db.execute(
        select(AIConversation)
        .where(
            AIConversation.organization_id == organization_id,
            AIConversation.visibility == "organization",
            AIConversation.purpose.is_(None),
        )
        .order_by(AIConversation.updated_at.desc())
        .limit(limit)
    )
    conversations = list(result.scalars())
    names = await user_names(db, {c.user_id for c in conversations})
    return [
        SharedConversationSummary(
            id=c.id, title=c.title, visibility=c.visibility, created_at=c.created_at,
            updated_at=c.updated_at, owner_id=c.user_id, owner_name=names.get(c.user_id, "Someone"),
        )
        for c in conversations
    ]


@router.get("/conversations", response_model=ApiResponse[list[SharedConversationSummary]])
async def list_shared_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    """Conversations their owners shared with the organization. Read-only."""

    return ApiResponse(success=True, data=await shared_conversations(db, current_user.organization_id))


class ActivityChange(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    environment: str
    change_type: str
    target_name: str
    status: str
    awaiting_approval: bool
    created_at: datetime
    executed_at: datetime | None
    created_by_name: str | None


class ActivityHealth(BaseModel):
    connection_id: uuid.UUID
    connection_name: str
    environment: str
    score: int
    grade: str
    scanned_at: datetime


class TeamActivity(BaseModel):
    open_work_items: list[WorkItemResponse]
    shared_conversations: list[SharedConversationSummary]
    changes: list[ActivityChange]
    health: list[ActivityHealth]


@router.get("/activity", response_model=ApiResponse[TeamActivity])
async def team_activity(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
    days: int = Query(default=14, ge=1, le=90),
):
    """What the team is working on: open work items, shared conversations,
    recent TM1 changes (and the ones waiting for approval), and the latest
    model health — on the connections this user may use."""

    organization_id = current_user.organization_id
    open_items = [
        i for i in await work_item_service.search(db, organization_id, limit=50)
        if i.status in ("open", "in_progress")
    ][:20]

    connections = {
        c.id: c for c in await tm1_integration_service.list_connections(db, organization_id)
        if await tm1_integration_service.may_access(db, c, user_id=current_user.id)
    }

    changes: list[ActivityChange] = []
    health: list[ActivityHealth] = []
    if connections:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = list((await db.execute(
            select(TM1Change)
            .where(TM1Change.connection_id.in_(connections), TM1Change.created_at >= since)
            .order_by(TM1Change.created_at.desc())
            .limit(50)
        )).scalars())
        names = await user_names(db, {r.created_by for r in rows})
        for r in rows:
            c = connections[r.connection_id]
            changes.append(ActivityChange(
                id=r.id, connection_id=c.id, connection_name=c.name, environment=c.environment,
                change_type=r.change_type, target_name=r.target_name, status=r.status,
                awaiting_approval=r.status == "draft" and not r.validation_errors,
                created_at=r.created_at, executed_at=r.executed_at, created_by_name=names.get(r.created_by),
            ))

        scans = (await db.execute(
            select(TM1HealthScan)
            .where(TM1HealthScan.connection_id.in_(connections))
            .order_by(TM1HealthScan.scanned_at.desc())
            .limit(200)
        )).scalars()
        seen = set()
        for s in scans:
            if s.connection_id in seen:
                continue
            seen.add(s.connection_id)
            c = connections[s.connection_id]
            health.append(ActivityHealth(
                connection_id=c.id, connection_name=c.name, environment=c.environment,
                score=s.score, grade=s.grade, scanned_at=s.scanned_at,
            ))

    return ApiResponse(
        success=True,
        data=TeamActivity(
            open_work_items=[WorkItemResponse.model_validate(i) for i in open_items],
            shared_conversations=(await shared_conversations(db, organization_id, limit=10)),
            changes=changes,
            health=health,
        ),
    )
