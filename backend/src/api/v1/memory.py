"""Engineering memory: list, add, approve, edit (new version), archive.

Reading needs knowledge.read. Approving, editing and archiving need
knowledge.write, checked in the service. Adding is open to anyone who can
read knowledge: without knowledge.write it lands as a proposal.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.engineering_memory_service import engineering_memory_service
from src.tm1.service import tm1_integration_service

router = APIRouter(prefix="/knowledge/memory", tags=["Engineering memory"])

Kind = Literal["convention", "sequence", "caution", "known_issue", "note"]


class MemoryCreate(BaseModel):
    kind: Kind
    text: str = Field(min_length=1, max_length=1000)
    connection_id: uuid.UUID | None = None
    object_type: Literal["cube", "dimension", "process", "chore", "rule"] | None = None
    object_name: str | None = Field(default=None, max_length=255)


class MemoryEdit(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    kind: Kind | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID | None
    object_type: str | None
    object_name: str | None
    kind: str
    text: str
    status: str
    source: str
    version: int
    supersedes: uuid.UUID | None
    created_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    rationale: str | None
    created_at: datetime


@router.get("", response_model=ApiResponse[list[MemoryResponse]])
async def list_memories(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
    status: Literal["proposed", "approved", "rejected", "archived"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
):
    memories = await engineering_memory_service.list(db, current_user.organization_id, status=status, query=q)
    return ApiResponse(success=True, data=[MemoryResponse.model_validate(m) for m in memories])


@router.post("", response_model=ApiResponse[MemoryResponse], status_code=201)
async def create_memory(
    body: MemoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    if body.connection_id is not None:
        # Memory about a connection only for one the user may use.
        await tm1_integration_service.get_connection(db, body.connection_id, current_user.organization_id)
    memory = await engineering_memory_service.create(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        kind=body.kind,
        text=body.text,
        source="human",
        connection_id=body.connection_id,
        object_type=body.object_type,
        object_name=body.object_name,
    )
    return ApiResponse(success=True, data=MemoryResponse.model_validate(memory))


@router.post("/{memory_id}/approve", response_model=ApiResponse[MemoryResponse])
async def approve_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    memory = await engineering_memory_service.decide(
        db, memory_id, current_user.organization_id, current_user.id, approve=True
    )
    return ApiResponse(success=True, data=MemoryResponse.model_validate(memory))


@router.post("/{memory_id}/reject", response_model=ApiResponse[MemoryResponse])
async def reject_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    memory = await engineering_memory_service.decide(
        db, memory_id, current_user.organization_id, current_user.id, approve=False
    )
    return ApiResponse(success=True, data=MemoryResponse.model_validate(memory))


@router.put("/{memory_id}", response_model=ApiResponse[MemoryResponse])
async def edit_memory(
    memory_id: uuid.UUID,
    body: MemoryEdit,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    """Saves a new version; the old one is kept, archived."""

    memory = await engineering_memory_service.edit(
        db, memory_id, current_user.organization_id, current_user.id, text=body.text, kind=body.kind
    )
    return ApiResponse(success=True, data=MemoryResponse.model_validate(memory))


@router.post("/{memory_id}/archive", response_model=ApiResponse[MemoryResponse])
async def archive_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    memory = await engineering_memory_service.archive(
        db, memory_id, current_user.organization_id, current_user.id
    )
    return ApiResponse(success=True, data=MemoryResponse.model_validate(memory))


@router.get("/{memory_id}/history", response_model=ApiResponse[list[MemoryResponse]])
async def memory_history(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    versions = await engineering_memory_service.history(db, memory_id, current_user.organization_id)
    return ApiResponse(success=True, data=[MemoryResponse.model_validate(m) for m in versions])
