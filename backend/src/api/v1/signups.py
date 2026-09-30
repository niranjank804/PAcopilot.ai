"""Sign-up requests across every workspace, for the platform owner.

Each sign-up without an organization code gets a private workspace of its
own (see auth_service), so the Users page — which lists one organization —
never shows it, and the workspace has no other admin to approve it. The
Super Admin approves or rejects it here instead.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_active_user
from src.core.exceptions import ConflictException, NotFoundException, PermissionDeniedException
from src.database.models.organization import Organization
from src.database.models.user import User
from src.database.session import get_db
from src.repositories.user_repository import user_repository
from src.repositories.user_role_repository import user_role_repository
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.audit_service import audit_service
from src.services.role_service import role_service

router = APIRouter(prefix="/admin/signups", tags=["Sign-ups"])

# Newest first; enough for any review, small enough for one page.
_LIST_LIMIT = 200


class SignupResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    registration_status: str
    created_at: datetime
    organization_name: str
    roles: list[str]


@contextmanager
def _every_organization(db: AsyncSession) -> Iterator[None]:
    """Lift the per-organization query filter (src/database/tenancy.py) for
    the few statements that must see every workspace. Only reached behind
    require_super_admin."""

    organization_id = db.info.pop("organization_id", None)
    try:
        yield
    finally:
        if organization_id is not None:
            db.info["organization_id"] = organization_id


async def require_super_admin(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_active_user),
) -> UserResponse:
    # Not a permission code: an organization's own admin holds every code
    # within its organization, and this reaches across organizations.
    if not await role_service.is_super_admin(db, current_user.id):
        raise PermissionDeniedException("Only a Super Admin can review sign-ups.")
    return current_user


@router.get("", response_model=ApiResponse[list[SignupResponse]])
async def list_signups(
    db: AsyncSession = Depends(get_db),
    _: UserResponse = Depends(require_super_admin),
    registration_status: str = Query(default="pending", pattern="^(pending|approved|rejected)$"),
):
    with _every_organization(db):
        rows = (
            await db.execute(
                select(User, Organization.name)
                .join(Organization, Organization.id == User.organization_id)
                .where(User.registration_status == registration_status)
                .order_by(User.created_at.desc())
                .limit(_LIST_LIMIT)
            )
        ).all()

        roles = await user_role_repository.role_names_by_user(
            db, [user.id for user, _name in rows]
        )

    return ApiResponse(
        success=True,
        data=[
            SignupResponse(
                id=user.id,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                registration_status=user.registration_status,
                created_at=user.created_at,
                organization_name=organization_name,
                roles=roles.get(user.id, []),
            )
            for user, organization_name in rows
        ],
    )


async def _decide(
    db: AsyncSession,
    user_id: uuid.UUID,
    decision: str,
    caller: UserResponse,
    http_request: Request,
) -> dict:
    with _every_organization(db):
        user = await user_repository.get_by_id(db, user_id)
        if user is None:
            raise NotFoundException("User not found.")
        if user.registration_status != "pending":
            raise ConflictException(f"This request was already {user.registration_status}.")

        user.registration_status = decision
        await user_repository.update(db, user)

    await audit_service.log(
        db,
        organization_id=user.organization_id,
        user_id=caller.id,
        action=f"{'approve' if decision == 'approved' else 'reject'}_signup",
        entity="User",
        entity_id=user.id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    return {"id": str(user.id), "registration_status": decision}


@router.post("/{user_id}/approve", response_model=ApiResponse[dict])
async def approve_signup(
    user_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    return ApiResponse(success=True, data=await _decide(db, user_id, "approved", caller, http_request))


@router.post("/{user_id}/reject", response_model=ApiResponse[dict])
async def reject_signup(
    user_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    caller: UserResponse = Depends(require_super_admin),
):
    return ApiResponse(success=True, data=await _decide(db, user_id, "rejected", caller, http_request))
