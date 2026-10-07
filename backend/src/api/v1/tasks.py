"""Task memory over HTTP: a person's own tasks, to see, rename, close or
reopen — the assistant reads and writes the same records each turn.

Every route is the owner's only and re-checks access to the task's TM1
connection (task_memory_service.get / search); another person's task, or
one on a connection the caller can no longer use, is "not found".
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.task_memory_service import SETTABLE, STATUSES, task_memory_service

router = APIRouter(prefix="/ai/tasks", tags=["Task memory"])


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal[SETTABLE] | None = None  # type: ignore[valid-type]
    # A person may add to the record too; nothing recorded is removed.
    finding: str | None = Field(default=None, max_length=2000)
    decision: str | None = Field(default=None, max_length=2000)
    next_step: str | None = Field(default=None, max_length=2000)


class TaskEventResponse(BaseModel):
    kind: str
    data: dict
    actor: str
    at: datetime


@router.get("", response_model=ApiResponse[list[dict]])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
    q: str | None = Query(default=None, max_length=200),
    status: Literal[STATUSES] | None = Query(default=None),  # type: ignore[valid-type]
    conversation_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
    work_item_id: uuid.UUID | None = None,
    object_name: str | None = Query(default=None, max_length=200),
    since_days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
):
    tasks = await task_memory_service.search(
        db, current_user.organization_id, current_user.id, query=q, status=status,
        conversation_id=conversation_id, connection_id=connection_id, work_item_id=work_item_id,
        object_name=object_name, since_days=since_days, limit=limit,
    )
    return ApiResponse(success=True, data=[task_memory_service.summary(t) for t in tasks])


@router.get("/{task_id}", response_model=ApiResponse[dict])
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    task = await task_memory_service.get(db, task_id, current_user.organization_id, current_user.id)
    await task_memory_service.refresh_actions(db, task, current_user.id)
    events = await task_memory_service.events(db, task)
    return ApiResponse(success=True, data={
        **task_memory_service.summary(task),
        "events": [TaskEventResponse(kind=e.kind, data=e.data, actor=e.actor, at=e.created_at).model_dump()
                   for e in events],
    })


@router.patch("/{task_id}", response_model=ApiResponse[dict])
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    """Rename, add a finding or decision, or set the status (completed,
    archived, reopened as active...). Recorded as the person, not the
    assistant."""

    task = await task_memory_service.get(db, task_id, current_user.organization_id, current_user.id)
    task = await task_memory_service.apply_update(
        db, task, current_user.id, actor="user", title=body.title, status=body.status,
        finding=body.finding, decision=body.decision, next_step=body.next_step,
    )
    return ApiResponse(success=True, data=task_memory_service.summary(task))
