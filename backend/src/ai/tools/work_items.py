"""Work items, for the agents.

"Investigate PBI #1234" starts from what the team already has: the
description, the root cause if someone wrote it, the linked conversations
and changes and where each change is in its life, and the documents
written so far.

The agents may also record a PBI the user pasted, save documents for it
(clarification email, design, test plan, test results, delivery) and link
the changes they drafted. These are PA-Copilot records, never TM1: nothing
here touches a server. Status, root cause and resolution stay with people
on the Team page.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import ConflictException, PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.services.work_item_document_service import KINDS, work_item_document_service
from src.services.work_item_service import work_item_service


async def _require(db, user_id, permission: str) -> None:
    if not await auth_repository.user_has_permission(db, user_id, permission):
        raise PermissionDeniedException(f"Missing permission: {permission}")


class GetWorkItemTool(Tool):

    name = "get_work_item"
    description = (
        "Read a team work item by its reference (for example 'PBI #1234' or "
        "'INC-88'): its description, status, the root cause and resolution "
        "people recorded, the conversations and TM1 changes linked to it, "
        "and its timeline (fix proposed, approved, applied, rolled back). "
        "Use when the user mentions a work item or ticket reference. "
        "Records the user cannot access are listed without detail."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "The work item reference, e.g. 'PBI #1234'."},
        },
        "required": ["reference"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(f"Missing permission: {self.required_permission}")

        reference = str(kwargs.get("reference") or "").strip()
        item = await work_item_service.find_by_reference(db, organization_id, reference) if reference else None
        if item is None:
            matches = await work_item_service.search(db, organization_id, query=reference, limit=5) if reference else []
            return json.dumps({
                "found": False,
                "reference": reference,
                "similar": [{"reference": m.reference, "title": m.title, "status": m.status} for m in matches],
            })

        timeline = await work_item_service.timeline(db, item, user_id)
        return json.dumps(
            {
                "found": True,
                "reference": item.reference,
                "title": item.title,
                "status": item.status,
                "description": item.description,
                "root_cause": item.root_cause,
                "resolution": item.resolution,
                "progress": {p["label"]: p["done"] for p in timeline["progress"]},
                "linked": [
                    {k: v for k, v in entry.items()
                     if k in ("kind", "title", "available", "status", "connection_name", "environment",
                              "owner_name", "note", "target_id")}
                    for entry in timeline["links"]
                ],
                "timeline": [
                    {"at": e["at"], "what": e["title"], "detail": e["detail"], "by": e["actor"]}
                    for e in timeline["events"]
                ],
                "documents": [
                    {
                        "title": d.title,
                        "kind": d.kind,
                        "version": d.version,
                        "content": d.content if len(d.content) <= 6000 else d.content[:6000] + "\n…(truncated)",
                    }
                    for d in await work_item_document_service.list(db, item)
                ],
                "evidence": "Team work item and the records linked to it, as they are now.",
            },
            default=str,
        )


class SaveWorkItemTool(Tool):

    name = "save_work_item"
    description = (
        "Record a PBI or ticket the user gave you (pasted text or a screenshot) "
        "as a team work item, or update the description of one that exists. "
        "Put the full description and the acceptance criteria in 'description' "
        "exactly as given, without inventing any. Use when the user asks you to "
        "work, track or document a PBI, so it can be read back later with "
        "get_work_item and its documents and changes attach to it. Creates a "
        "PA-Copilot record only; nothing is written to TM1."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "e.g. 'PBI 4076293'."},
            "title": {"type": "string"},
            "description": {"type": "string", "description": "Description and acceptance criteria, verbatim."},
        },
        "required": ["reference", "title"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _require(db, user_id, self.required_permission)
        reference = str(kwargs.get("reference") or "").strip()
        title = str(kwargs.get("title") or "").strip()
        description = kwargs.get("description")
        item = await work_item_service.find_by_reference(db, organization_id, reference) if reference else None
        if item is None:
            item = await work_item_service.create(
                db, organization_id=organization_id, user_id=user_id,
                reference=reference, title=title, description=description,
            )
            created = True
        else:
            changes = {"title": title} if title else {}
            if description:
                changes["description"] = description
            await work_item_service.update(db, item, user_id, changes)
            created = False
        return json.dumps({
            "saved": True,
            "created": created,
            "reference": item.reference,
            "title": item.title,
            "work_item_id": str(item.id),
            "page": f"/team/{item.id}",
        })


class SaveWorkItemDocumentTool(Tool):

    name = "save_work_item_document"
    description = (
        "Save a document on a work item, in Markdown: the requirements gaps, "
        "a clarification email (a draft; never sent), the design, the TI code "
        "listing, the test plan, test results, evidence, the delivery document "
        "or the completion email. Saving a title that exists replaces it as a "
        "new version. People read, edit and download it (Word or Markdown) on "
        "the work item. State only what you verified; mark anything assumed "
        "or not yet run as such. Creates a PA-Copilot record only."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "The work item reference."},
            "kind": {"type": "string", "enum": list(KINDS)},
            "title": {"type": "string", "description": "e.g. 'Clarification email' or 'Test results'."},
            "content": {"type": "string", "description": "The document, in Markdown."},
        },
        "required": ["reference", "kind", "title", "content"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _require(db, user_id, self.required_permission)
        reference = str(kwargs.get("reference") or "").strip()
        item = await work_item_service.find_by_reference(db, organization_id, reference) if reference else None
        if item is None:
            return json.dumps({"saved": False, "error": f"No work item {reference!r}; save it with save_work_item first."})
        document = await work_item_document_service.save(
            db, item, user_id, kind=str(kwargs.get("kind") or "notes"), title=str(kwargs.get("title") or ""),
            content=str(kwargs.get("content") or ""), by_assistant=True,
        )
        return json.dumps({
            "saved": True,
            "reference": item.reference,
            "title": document.title,
            "version": document.version,
            "page": f"/team/{item.id}",
        })


class LinkWorkItemChangeTool(Tool):

    name = "link_change_to_work_item"
    description = (
        "Attach a TM1 change you drafted (its change_id from propose_* tools) to "
        "a work item, so the work item's timeline shows its review, approval, "
        "deployment and rollback. Changes nothing on TM1."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "reference": {"type": "string"},
            "change_id": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["reference", "change_id"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _require(db, user_id, self.required_permission)
        reference = str(kwargs.get("reference") or "").strip()
        item = await work_item_service.find_by_reference(db, organization_id, reference) if reference else None
        if item is None:
            return json.dumps({"linked": False, "error": f"No work item {reference!r}."})
        try:
            change_id = uuid.UUID(str(kwargs.get("change_id")))
        except ValueError:
            return json.dumps({"linked": False, "error": "change_id is not a valid id."})
        try:
            await work_item_service.link(db, item, user_id, kind="change", target_id=change_id,
                                         note=kwargs.get("note"))
        except ConflictException:
            return json.dumps({"linked": True, "already": True, "reference": item.reference})
        return json.dumps({"linked": True, "reference": item.reference})
