import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.audit_log import AuditLog
from src.repositories.audit_log_repository import audit_log_repository


class AuditService:

    async def log(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        action: str,
        entity: str,
        entity_id: uuid.UUID | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:

        audit_log = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return await audit_log_repository.create(
            db,
            audit_log,
        )


    async def record(
        self,
        db: AsyncSession,
        user,
        action: str,
        entity: str,
        entity_id: uuid.UUID | None = None,
        values: dict | None = None,
        request=None,
    ) -> AuditLog:
        """log() for the common case: the acting user and, when given, the
        request's address and browser. The request log keeps those for
        every request anyway; this makes the action itself searchable."""

        ip = user_agent = None
        if request is not None:
            from src.core.rate_limit import client_ip_of

            ip = client_ip_of(request)
            user_agent = request.headers.get("user-agent")
        return await self.log(
            db,
            organization_id=getattr(user, "organization_id", None),
            user_id=getattr(user, "id", None),
            action=action,
            entity=entity,
            entity_id=entity_id,
            new_values=values,
            ip_address=ip,
            user_agent=user_agent,
        )


audit_service = AuditService()
