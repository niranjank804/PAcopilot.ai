import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.audit_log import AuditLog


class AuditLogRepository:

    async def create(
        self,
        db: AsyncSession,
        audit_log: AuditLog,
    ) -> AuditLog:

        db.add(audit_log)

        await db.flush()

        await db.refresh(audit_log)

        return audit_log

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:

        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return list(result.scalars().all())


audit_log_repository = AuditLogRepository()
