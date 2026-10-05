"""Work items: one piece of engineering work and everything that happened to it.

A work item ("PBI #1234: Workforce load fails on the new year") holds no
copies. Conversations and TM1 changes are linked to it, and its timeline is
read from those records each time, so it shows what they say now: the
investigation, the proposed fix, who approved and applied it, how it was
verified, and whether it was rolled back.

The rules:

* A work item never widens access. A linked conversation appears only if
  the viewer may read it (their own, or shared with the organization); a
  linked change appears only if the viewer may use its TM1 connection.
  Anything else shows as an entry the viewer cannot open, with no detail.
* Only a shared conversation can be linked: a work item is for the team,
  and a private conversation would be a hole in its story.
* People write the root cause and resolution. Nothing fills them in.
* Every create, update, link and unlink is in the audit log.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException, ValidationException
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_message import AIMessage
from src.database.models.audit_log import AuditLog
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_connection import TM1Connection
from src.database.models.user import User
from src.database.models.work_item import WorkItem, WorkItemLink
from src.services.audit_service import audit_service
from src.tm1.deployment.change_service import change_service
from src.tm1.service import tm1_integration_service

STATUSES = ("open", "in_progress", "resolved", "closed")
LINK_KINDS = ("conversation", "change")
EDITABLE = ("title", "description", "status", "root_cause", "resolution")


def can_read_conversation(conversation: AIConversation, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        conversation.organization_id == organization_id
        and conversation.purpose is None
        and (conversation.user_id == user_id or conversation.visibility == "organization")
    )


async def user_names(db: AsyncSession, user_ids) -> dict[uuid.UUID, str]:
    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.first_name, User.last_name).where(User.id.in_(ids)))
    return {row.id: f"{row.first_name} {row.last_name}".strip() for row in rows}


class WorkItemService:

    def _text(self, value: str | None, field: str, limit: int, *, required: bool = False) -> str | None:
        value = (value or "").strip()
        if not value:
            if required:
                raise ValidationException(f"A work item needs a {field}.")
            return None
        if len(value) > limit:
            raise ValidationException(f"Keep the {field} under {limit} characters.")
        return value

    async def _audit(self, db, item: WorkItem, user_id, action: str, new_values: dict, old_values: dict | None = None):
        await audit_service.log(
            db,
            organization_id=item.organization_id,
            user_id=user_id,
            action=action,
            entity="WorkItem",
            entity_id=item.id,
            old_values=old_values,
            new_values=new_values,
        )

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        reference: str,
        title: str,
        description: str | None = None,
    ) -> WorkItem:
        reference = self._text(reference, "reference", 50, required=True)
        if await self.find_by_reference(db, organization_id, reference) is not None:
            raise ConflictException(f"There is already a work item {reference}.")
        item = WorkItem(
            organization_id=organization_id,
            reference=reference,
            title=self._text(title, "title", 255, required=True),
            description=self._text(description, "description", 10_000),
            status="open",
            created_by=user_id,
        )
        db.add(item)
        await db.flush()
        await self._audit(db, item, user_id, "work_item_created", {"reference": item.reference, "title": item.title})
        return item

    async def get(self, db: AsyncSession, work_item_id: uuid.UUID, organization_id: uuid.UUID) -> WorkItem:
        item = await db.get(WorkItem, work_item_id)
        if item is None or item.organization_id != organization_id:
            raise NotFoundException("Work item not found.")
        return item

    async def find_by_reference(self, db: AsyncSession, organization_id: uuid.UUID, reference: str) -> WorkItem | None:
        result = await db.execute(
            select(WorkItem).where(
                WorkItem.organization_id == organization_id,
                func.lower(WorkItem.reference) == reference.strip().lower(),
            )
        )
        return result.scalars().first()

    async def search(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        query: str | None = None,
        limit: int = 200,
    ) -> list[WorkItem]:
        statement = select(WorkItem).where(WorkItem.organization_id == organization_id)
        if status:
            statement = statement.where(WorkItem.status == status)
        if query and query.strip():
            like = f"%{query.strip()}%"
            statement = statement.where(or_(WorkItem.reference.ilike(like), WorkItem.title.ilike(like)))
        statement = statement.order_by(WorkItem.updated_at.desc()).limit(limit)
        return list((await db.execute(statement)).scalars())

    async def update(self, db: AsyncSession, item: WorkItem, user_id: uuid.UUID, changes: dict) -> WorkItem:
        limits = {"title": 255, "description": 10_000, "root_cause": 10_000, "resolution": 10_000}
        old, new = {}, {}
        for field, value in changes.items():
            if field not in EDITABLE:
                continue
            if field == "status":
                if value not in STATUSES:
                    raise ValidationException(f"status must be one of: {', '.join(STATUSES)}.")
            else:
                value = self._text(value, field.replace("_", " "), limits[field], required=field == "title")
            if getattr(item, field) != value:
                old[field], new[field] = getattr(item, field), value
                setattr(item, field, value)
        if new:
            await db.flush()
            await db.refresh(item)
            await self._audit(
                db, item, user_id, "work_item_updated",
                {k: (v[:200] if isinstance(v, str) else v) for k, v in new.items()},
                {k: (v[:200] if isinstance(v, str) else v) for k, v in old.items()},
            )
        return item

    async def _conversation_for(self, db, conversation_id, organization_id, user_id) -> AIConversation:
        conversation = await db.get(AIConversation, conversation_id)
        if conversation is None or not can_read_conversation(conversation, organization_id, user_id):
            raise NotFoundException("Conversation not found.")
        return conversation

    async def _change_for(self, db, change_id, organization_id, user_id) -> tuple[TM1Change, TM1Connection]:
        change = await db.get(TM1Change, change_id)
        if change is None or change.organization_id != organization_id:
            raise NotFoundException("Change not found.")
        connection = await db.get(TM1Connection, change.connection_id)
        if connection is None or not await tm1_integration_service.may_access(db, connection, user_id=user_id):
            # Same answer as a missing change: a private connection's
            # changes are not disclosed.
            raise NotFoundException("Change not found.")
        return change, connection

    async def link(
        self,
        db: AsyncSession,
        item: WorkItem,
        user_id: uuid.UUID,
        *,
        kind: str,
        target_id: uuid.UUID,
        note: str | None = None,
    ) -> WorkItemLink:
        if kind not in LINK_KINDS:
            raise ValidationException(f"kind must be one of: {', '.join(LINK_KINDS)}.")
        if kind == "conversation":
            conversation = await self._conversation_for(db, target_id, item.organization_id, user_id)
            if conversation.visibility != "organization":
                raise ConflictException(
                    "Share the conversation with your organization first, so the team can read it."
                )
        else:
            await self._change_for(db, target_id, item.organization_id, user_id)

        existing = await db.execute(
            select(WorkItemLink).where(
                WorkItemLink.work_item_id == item.id,
                WorkItemLink.kind == kind,
                WorkItemLink.target_id == target_id,
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictException(f"That {kind} is already linked to {item.reference}.")

        link = WorkItemLink(
            organization_id=item.organization_id,
            work_item_id=item.id,
            kind=kind,
            target_id=target_id,
            note=self._text(note, "note", 2000),
            linked_by=user_id,
        )
        db.add(link)
        await db.flush()
        await self._audit(db, item, user_id, "work_item_linked", {"kind": kind, "target_id": str(target_id)})
        return link

    async def unlink(self, db: AsyncSession, item: WorkItem, link_id: uuid.UUID, user_id: uuid.UUID) -> None:
        link = await db.get(WorkItemLink, link_id)
        if link is None or link.work_item_id != item.id:
            raise NotFoundException("Link not found.")
        await db.delete(link)
        await db.flush()
        await self._audit(db, item, user_id, "work_item_unlinked", {"kind": link.kind, "target_id": str(link.target_id)})

    async def links(self, db: AsyncSession, item: WorkItem) -> list[WorkItemLink]:
        result = await db.execute(
            select(WorkItemLink).where(WorkItemLink.work_item_id == item.id).order_by(WorkItemLink.created_at)
        )
        return list(result.scalars())

    async def items_linked_to(self, db: AsyncSession, organization_id: uuid.UUID, target_id: uuid.UUID) -> list[WorkItem]:
        result = await db.execute(
            select(WorkItem)
            .join(WorkItemLink, WorkItemLink.work_item_id == WorkItem.id)
            .where(WorkItem.organization_id == organization_id, WorkItemLink.target_id == target_id)
        )
        return list(result.scalars().unique())

    async def timeline(self, db: AsyncSession, item: WorkItem, user_id: uuid.UUID) -> dict:
        """The work item's story, oldest first, from the records as they are now.

        Returns the events, the linked records (each marked available or
        not for this viewer), and progress through the stages a fix goes
        through: investigation, root cause, proposed fix, approval,
        deployment, verification.
        """

        events: list[dict] = []
        linked: list[dict] = []
        actors: set = {item.created_by}

        def event(at: datetime, kind: str, title: str, *, detail=None, actor=None, link_id=None):
            if actor:
                actors.add(actor)
            events.append({"at": at, "kind": kind, "title": title, "detail": detail,
                           "actor_id": actor, "link_id": link_id})

        event(item.created_at, "created", f"{item.reference} opened", detail=item.title, actor=item.created_by)

        # People's edits, from the audit log: status moves and the root
        # cause and resolution being written.
        audit = await db.execute(
            select(AuditLog)
            .where(AuditLog.entity == "WorkItem", AuditLog.entity_id == item.id,
                   AuditLog.action == "work_item_updated")
            .order_by(AuditLog.created_at)
        )
        for row in audit.scalars():
            values = row.new_values or {}
            if "status" in values:
                event(row.created_at, "status", f"Status set to {values['status'].replace('_', ' ')}", actor=row.user_id)
            if values.get("root_cause"):
                event(row.created_at, "root_cause", "Root cause recorded", detail=values["root_cause"], actor=row.user_id)
            if values.get("resolution"):
                event(row.created_at, "resolution", "Resolution recorded", detail=values["resolution"], actor=row.user_id)

        if item.kind == "incident":
            from src.services.incident_service import incident_service

            for look in reversed(await incident_service.investigations(db, item, user_id) or []):
                event(look.created_at, "investigation_run", "Investigated", detail=look.summary, actor=look.run_by)

        visible_changes: list[TM1Change] = []
        conversations = 0
        for link in await self.links(db, item):
            actors.add(link.linked_by)
            entry = {"link_id": link.id, "kind": link.kind, "target_id": link.target_id, "note": link.note,
                     "linked_by": link.linked_by, "linked_at": link.created_at, "available": False}

            if link.kind == "conversation":
                conversation = await db.get(AIConversation, link.target_id)
                if conversation is None or not can_read_conversation(conversation, item.organization_id, user_id):
                    entry["title"] = "A conversation that is no longer shared"
                    event(link.created_at, "unavailable", entry["title"], link_id=link.id)
                else:
                    conversations += 1
                    count = await db.scalar(
                        select(func.count()).select_from(AIMessage).where(AIMessage.conversation_id == conversation.id)
                    )
                    entry.update(available=True, title=conversation.title or "Untitled conversation",
                                 owner_id=conversation.user_id, messages=count or 0)
                    actors.add(conversation.user_id)
                    event(conversation.created_at, "investigation",
                          f"Investigation: {entry['title']}", detail=link.note,
                          actor=conversation.user_id, link_id=link.id)
            else:
                change = await db.get(TM1Change, link.target_id)
                connection = await db.get(TM1Connection, change.connection_id) if change else None
                if (
                    change is None
                    or connection is None
                    or not await tm1_integration_service.may_access(db, connection, user_id=user_id)
                ):
                    entry["title"] = "A change on a TM1 connection you cannot use"
                    event(link.created_at, "unavailable", entry["title"], link_id=link.id)
                else:
                    visible_changes.append(change)
                    what = f"{change.change_type.replace('_', ' ')} · {change.target_name}"
                    entry.update(available=True, title=what, status=change.status,
                                 connection_id=connection.id, connection_name=connection.name,
                                 environment=connection.environment)
                    where = f"{connection.name} ({connection.environment.upper()})"
                    for step in change_service.lifecycle(change):
                        if step["at"] is None or step["state"] not in ("done", "failed"):
                            continue
                        if step["key"] in ("analyzed", "diff", "snapshot"):
                            continue  # same moment as another step; adds noise, not information
                        actor = change.created_by if step["key"] in ("requested", "validated") else change.executed_by
                        label = {"requested": "Fix proposed", "validated": "Validated",
                                 "approval": "Approved", "deployed": "Applied", "verified": "Verified",
                                 "rolled_back": "Rolled back"}.get(step["key"], step["label"])
                        if step["state"] == "failed":
                            label = f"{label}: failed"
                        event(step["at"], f"change_{step['key']}", f"{label} — {what}",
                              detail=step["detail"] or where, actor=actor, link_id=link.id)
            linked.append(entry)

        executed = [c for c in visible_changes if c.status in ("executed", "rolled_back")]
        progress = [
            {"key": "investigation", "label": "Investigation", "done": conversations > 0},
            {"key": "root_cause", "label": "Root cause", "done": bool(item.root_cause)},
            {"key": "fix", "label": "Proposed fix", "done": bool(visible_changes)},
            {"key": "approval", "label": "Approval", "done": bool(executed)},
            {"key": "deployment", "label": "Deployment", "done": any(c.status == "executed" for c in visible_changes)},
            {"key": "verification", "label": "Verified", "done": any(
                c.status == "executed" for c in visible_changes) and item.status in ("resolved", "closed")},
        ]

        names = await user_names(db, actors | {e.get("owner_id") for e in linked})
        for e in events:
            e["actor"] = names.get(e.pop("actor_id"))
        for entry in linked:
            entry["linked_by_name"] = names.get(entry["linked_by"])
            if entry.get("owner_id"):
                entry["owner_name"] = names.get(entry["owner_id"])

        events.sort(key=lambda e: e["at"])
        return {"events": events, "links": linked, "progress": progress,
                "created_by_name": names.get(item.created_by)}


work_item_service = WorkItemService()
