import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException, PermissionDeniedException, ValidationException
from src.database.models.user import User
from src.repositories.user_repository import user_repository
from src.services.role_service import role_service


async def _deactivated_by_platform(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the platform owner's latest decision on this person was to
    deactivate them, so a workspace admin cannot quietly undo it."""

    from sqlalchemy import select

    from src.database.models.audit_log import AuditLog

    latest = (await db.execute(
        select(AuditLog.action)
        .where(
            AuditLog.entity_id == user_id,
            AuditLog.action.in_(("platform_deactivate_user", "platform_activate_user")),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return latest == "platform_deactivate_user"


class UserService:

    async def list_users(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        registration_status: str | None = None,
    ) -> list[User]:

        return await user_repository.list_by_organization(
            db,
            organization_id,
            registration_status,
        )

    async def _get_pending_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
    ) -> User:

        user = await user_repository.get_by_id(db, user_id)

        if user is None or user.organization_id != caller_organization_id:
            raise NotFoundException("User not found.")

        if user.registration_status != "pending":
            raise ConflictException(
                f"This request was already {user.registration_status}."
            )

        return user

    async def approve_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
        role_id: uuid.UUID | None,
        caller_user_id: uuid.UUID | None = None,
    ) -> User:

        user = await self._get_pending_user(db, user_id, caller_organization_id)

        user.registration_status = "approved"
        user = await user_repository.update(db, user)

        if role_id is not None:
            await role_service.assign_role(
                db,
                user.id,
                role_id,
                caller_organization_id,
                caller_user_id=caller_user_id,
            )

        return user

    async def reject_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
    ) -> User:

        user = await self._get_pending_user(db, user_id, caller_organization_id)

        user.registration_status = "rejected"

        return await user_repository.update(db, user)

    async def set_active(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
        caller_user_id: uuid.UUID,
        is_active: bool,
    ) -> User:

        if user_id == caller_user_id:
            raise ValidationException(
                "You cannot deactivate your own account."
            )

        user = await user_repository.get_by_id(db, user_id)

        if user is None or user.organization_id != caller_organization_id:
            raise NotFoundException("User not found.")

        if is_active and await _deactivated_by_platform(db, user.id):
            raise PermissionDeniedException(
                "This account was deactivated by the platform administrator; "
                "only they can reactivate it."
            )

        user.is_active = is_active
        if not is_active:
            # Deactivation ends every session at once, not just the next
            # request each token makes.
            from src.services.token_revocation_service import token_revocation_service

            await token_revocation_service.revoke_all_for_user(db, user.id)

        return await user_repository.update(db, user)


user_service = UserService()
