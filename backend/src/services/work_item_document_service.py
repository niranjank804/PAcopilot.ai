"""Documents kept with a work item (models.work_item.WorkItemDocument).

The written side of a PBI — clarification email, design, test plan, test
results, delivery document, completion email — lives here, so the work
needs no file system: the assistant drafts a document, a person reads and
edits it on the work item, and downloads it as Markdown or Word.

Saving a title that exists replaces its text and raises the version. Every
save and delete is in the audit log, with who saved it and whether the
assistant drafted it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.database.models.work_item import WorkItem, WorkItemDocument
from src.services.audit_service import audit_service

KINDS = (
    "requirements",
    "clarification_email",
    "design",
    "code",
    "test_plan",
    "test_results",
    "evidence",
    "delivery",
    "completion_email",
    "notes",
)
MAX_CONTENT = 200_000
MAX_DOCUMENTS = 50


class WorkItemDocumentService:

    async def list(self, db: AsyncSession, item: WorkItem) -> list[WorkItemDocument]:
        rows = await db.execute(
            select(WorkItemDocument)
            .where(WorkItemDocument.work_item_id == item.id)
            .order_by(WorkItemDocument.created_at)
        )
        return list(rows.scalars())

    async def get(self, db: AsyncSession, item: WorkItem, document_id: uuid.UUID) -> WorkItemDocument:
        document = await db.get(WorkItemDocument, document_id)
        if document is None or document.work_item_id != item.id:
            raise NotFoundException("Document not found.")
        return document

    async def save(
        self,
        db: AsyncSession,
        item: WorkItem,
        user_id: uuid.UUID,
        *,
        kind: str,
        title: str,
        content: str,
        by_assistant: bool = False,
    ) -> WorkItemDocument:
        if kind not in KINDS:
            raise ValidationException(f"kind must be one of: {', '.join(KINDS)}.")
        title = (title or "").strip()
        if not title or len(title) > 200:
            raise ValidationException("A document needs a title of at most 200 characters.")
        content = content or ""
        if not content.strip():
            raise ValidationException("A document needs some content.")
        if len(content) > MAX_CONTENT:
            raise ValidationException(f"Keep a document under {MAX_CONTENT:,} characters.")

        existing = (await db.execute(
            select(WorkItemDocument).where(
                WorkItemDocument.work_item_id == item.id, WorkItemDocument.title == title,
            )
        )).scalar_one_or_none()

        if existing is None:
            count = len(await self.list(db, item))
            if count >= MAX_DOCUMENTS:
                raise ValidationException(f"A work item holds at most {MAX_DOCUMENTS} documents.")
            existing = WorkItemDocument(
                organization_id=item.organization_id, work_item_id=item.id, kind=kind, title=title,
                content=content, version=1, updated_by=user_id, drafted_by_assistant=by_assistant,
            )
            db.add(existing)
            action = "work_item_document_created"
        else:
            existing.kind = kind
            existing.content = content
            existing.version += 1
            existing.updated_by = user_id
            existing.drafted_by_assistant = by_assistant
            action = "work_item_document_updated"

        await db.flush()
        await db.refresh(existing)
        await audit_service.log(
            db,
            organization_id=item.organization_id,
            user_id=user_id,
            action=action,
            entity="WorkItemDocument",
            entity_id=existing.id,
            new_values={"work_item": item.reference, "title": title, "kind": kind,
                        "version": existing.version, "by_assistant": by_assistant},
        )
        return existing

    async def delete(self, db: AsyncSession, item: WorkItem, document_id: uuid.UUID, user_id: uuid.UUID) -> None:
        document = await self.get(db, item, document_id)
        await audit_service.log(
            db,
            organization_id=item.organization_id,
            user_id=user_id,
            action="work_item_document_deleted",
            entity="WorkItemDocument",
            entity_id=document.id,
            old_values={"work_item": item.reference, "title": document.title, "kind": document.kind},
        )
        await db.delete(document)
        await db.flush()


work_item_document_service = WorkItemDocumentService()
