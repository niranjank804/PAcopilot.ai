"""Engineering memory: organization knowledge people vouch for.

The rules, in one place:

* A person with knowledge.write who writes a memory vouches for it: it is
  approved at once. Anyone else's, and every one the assistant suggests,
  starts as `proposed`.
* Only approved memories reach the assistant. A proposal is invisible to
  every conversation until a person with knowledge.write approves it — the
  assistant's own guesses never become permanent memory by themselves.
* Edits never overwrite: an edit is a new version that `supersedes` the
  old one, which is archived. History shows what the assistant was told,
  and when.
* Every create, approve, reject, edit and archive is in the audit log.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException, PermissionDeniedException, ValidationException
from src.database.models.engineering_memory import EngineeringMemory
from src.repositories.auth_repository import auth_repository
from src.services.audit_service import audit_service

KINDS = ("convention", "sequence", "caution", "known_issue", "note")
OBJECT_TYPES = ("cube", "dimension", "process", "chore", "rule")
MAX_TEXT = 1000
# Approved memories put in one conversation's context.
MAX_IN_PROMPT = 40


class EngineeringMemoryService:

    async def _can_vouch(self, db: AsyncSession, user_id: uuid.UUID) -> bool:
        return await auth_repository.user_has_permission(db, user_id, "knowledge.write")

    async def _audit(self, db, memory: EngineeringMemory, user_id, action: str) -> None:
        await audit_service.log(
            db,
            organization_id=memory.organization_id,
            user_id=user_id,
            action=action,
            entity="EngineeringMemory",
            entity_id=memory.id,
            new_values={"status": memory.status, "version": memory.version, "text": memory.text[:200]},
        )

    def _validate(self, kind: str, text: str, object_type: str | None) -> str:
        if kind not in KINDS:
            raise ValidationException(f"kind must be one of: {', '.join(KINDS)}.")
        if object_type is not None and object_type not in OBJECT_TYPES:
            raise ValidationException(f"object_type must be one of: {', '.join(OBJECT_TYPES)}.")
        text = (text or "").strip()
        if not text:
            raise ValidationException("A memory needs some text.")
        if len(text) > MAX_TEXT:
            raise ValidationException(f"Keep a memory under {MAX_TEXT} characters; split it if needed.")
        return text

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        kind: str,
        text: str,
        source: str,
        connection_id: uuid.UUID | None = None,
        object_type: str | None = None,
        object_name: str | None = None,
        rationale: str | None = None,
    ) -> EngineeringMemory:
        text = self._validate(kind, text, object_type)
        vouched = source == "human" and await self._can_vouch(db, user_id)

        memory = EngineeringMemory(
            organization_id=organization_id,
            connection_id=connection_id,
            object_type=object_type,
            object_name=(object_name or "").strip() or None,
            kind=kind,
            text=text,
            status="approved" if vouched else "proposed",
            source=source,
            version=1,
            created_by=user_id,
            decided_by=user_id if vouched else None,
            decided_at=datetime.now(timezone.utc) if vouched else None,
            rationale=(rationale or "").strip()[:2000] or None,
        )
        db.add(memory)
        await db.flush()
        await self._audit(db, memory, user_id, "memory_created" if vouched else "memory_proposed")
        return memory

    async def get(self, db, memory_id: uuid.UUID, organization_id: uuid.UUID) -> EngineeringMemory:
        memory = await db.get(EngineeringMemory, memory_id)
        if memory is None or memory.organization_id != organization_id:
            raise NotFoundException("Memory not found.")
        return memory

    async def decide(
        self, db, memory_id: uuid.UUID, organization_id: uuid.UUID, user_id: uuid.UUID, *, approve: bool
    ) -> EngineeringMemory:
        if not await self._can_vouch(db, user_id):
            raise PermissionDeniedException("Approving memory needs the knowledge.write permission.")
        memory = await self.get(db, memory_id, organization_id)
        if memory.status != "proposed":
            raise ConflictException(f"This memory is already {memory.status}.")
        memory.status = "approved" if approve else "rejected"
        memory.decided_by = user_id
        memory.decided_at = datetime.now(timezone.utc)
        await db.flush()
        await self._audit(db, memory, user_id, "memory_approved" if approve else "memory_rejected")
        return memory

    async def edit(
        self, db, memory_id: uuid.UUID, organization_id: uuid.UUID, user_id: uuid.UUID, *, text: str, kind: str | None = None
    ) -> EngineeringMemory:
        """A new version; the old one is archived, never overwritten."""

        if not await self._can_vouch(db, user_id):
            raise PermissionDeniedException("Editing memory needs the knowledge.write permission.")
        old = await self.get(db, memory_id, organization_id)
        if old.status != "approved":
            raise ConflictException("Only an approved memory can be edited; approve or reject a proposal first.")
        new_kind = kind or old.kind
        text = self._validate(new_kind, text, old.object_type)

        old.status = "archived"
        new = EngineeringMemory(
            organization_id=old.organization_id,
            connection_id=old.connection_id,
            object_type=old.object_type,
            object_name=old.object_name,
            kind=new_kind,
            text=text,
            status="approved",
            source="human",
            version=old.version + 1,
            supersedes=old.id,
            created_by=user_id,
            decided_by=user_id,
            decided_at=datetime.now(timezone.utc),
        )
        db.add(new)
        await db.flush()
        await self._audit(db, new, user_id, "memory_edited")
        return new

    async def archive(self, db, memory_id: uuid.UUID, organization_id: uuid.UUID, user_id: uuid.UUID) -> EngineeringMemory:
        if not await self._can_vouch(db, user_id):
            raise PermissionDeniedException("Archiving memory needs the knowledge.write permission.")
        memory = await self.get(db, memory_id, organization_id)
        if memory.status == "archived":
            return memory
        memory.status = "archived"
        await db.flush()
        await self._audit(db, memory, user_id, "memory_archived")
        return memory

    async def history(self, db, memory_id: uuid.UUID, organization_id: uuid.UUID) -> list[EngineeringMemory]:
        """This version and every one before it, newest first."""

        versions = [await self.get(db, memory_id, organization_id)]
        while versions[-1].supersedes and len(versions) < 50:
            earlier = await db.get(EngineeringMemory, versions[-1].supersedes)
            if earlier is None or earlier.organization_id != organization_id:
                break
            versions.append(earlier)
        return versions

    async def search(
        self,
        db,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        connection_id: uuid.UUID | None = None,
        query: str | None = None,
        limit: int = 200,
    ) -> list[EngineeringMemory]:
        statement = select(EngineeringMemory).where(EngineeringMemory.organization_id == organization_id)
        if status:
            statement = statement.where(EngineeringMemory.status == status)
        if connection_id:
            statement = statement.where(
                or_(EngineeringMemory.connection_id == connection_id, EngineeringMemory.connection_id.is_(None))
            )
        if query:
            like = f"%{query.strip()}%"
            statement = statement.where(
                or_(EngineeringMemory.text.ilike(like), EngineeringMemory.object_name.ilike(like))
            )
        statement = statement.order_by(EngineeringMemory.updated_at.desc()).limit(limit)
        return list((await db.execute(statement)).scalars())

    async def prompt_block(
        self, db, organization_id: uuid.UUID, connection_ids: list[uuid.UUID]
    ) -> str | None:
        """Approved memory for the system prompt: org-wide ones and those
        about the connections this conversation can use."""

        statement = (
            select(EngineeringMemory)
            .where(
                EngineeringMemory.organization_id == organization_id,
                EngineeringMemory.status == "approved",
                or_(
                    EngineeringMemory.connection_id.is_(None),
                    EngineeringMemory.connection_id.in_(connection_ids or [uuid.uuid4()]),
                ),
            )
            .order_by(EngineeringMemory.updated_at.desc())
            .limit(MAX_IN_PROMPT)
        )
        memories = list((await db.execute(statement)).scalars())
        if not memories:
            return None

        lines = []
        for m in memories:
            about = f" [{m.object_type} {m.object_name}]" if m.object_type and m.object_name else ""
            lines.append(f"- ({m.kind}){about} {m.text} — approved {m.decided_at:%Y-%m-%d}")
        return (
            "Approved engineering memory — ORGANIZATION KNOWLEDGE, vouched for by "
            "people in this organization. Follow it, cite it as organization "
            "knowledge (not as something read from TM1), and say so if live TM1 "
            "evidence contradicts it:\n" + "\n".join(lines)
        )


engineering_memory_service = EngineeringMemoryService()
