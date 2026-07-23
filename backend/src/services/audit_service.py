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


audit_service = AuditService()
