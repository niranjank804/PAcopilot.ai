"""Task memory, for the agents: record what this task has established, and
find earlier tasks to pick up again.

These write PA-Copilot's own task record (models.ai_task), never TM1 and
never engineering memory. A finding stays task memory; organization
knowledge goes through propose_engineering_memory and its approval, and
only when the user asks for it.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.database.models.ai_conversation import AIConversation
from src.repositories.auth_repository import auth_repository
from src.services.task_memory_service import SETTABLE, task_memory_service


async def _conversation(db: AsyncSession, conversation_id, organization_id, user_id) -> AIConversation | None:
    conversation = await db.get(AIConversation, conversation_id) if conversation_id else None
    if conversation is None or conversation.organization_id != organization_id or conversation.user_id != user_id:
        return None
    return conversation


class UpdateTaskMemoryTool(Tool):

    name = "update_task_memory"
    needs_conversation = True
    description = (
        "Record, in this conversation's task memory, what the task has established: a finding "
        "(a root cause or fact you verified — say how), a decision the user made, a blocker, the "
        "next step, or a new status (waiting_for_user, blocked, completed, failed, cancelled). "
        "Call it when you establish a root cause, when the user decides something, and when the "
        "task is done. It adds to the record and never rewrites what was recorded before. Use "
        "start_new_task (with a title) only when the user clearly moves to an unrelated objective, "
        "and resume_task_id to continue an earlier task found with search_task_memory. This is "
        "task memory, not organization knowledge: nothing here becomes engineering memory."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "finding": {"type": "string"},
            "decision": {"type": "string"},
            "blocker": {"type": "string"},
            "next_step": {"type": "string"},
            "status": {"type": "string", "enum": [s for s in SETTABLE if s != "archived"]},
            "title": {"type": "string", "description": "A better title for the task."},
            "objective": {"type": "string"},
            "start_new_task": {"type": "boolean"},
            "resume_task_id": {"type": "string", "description": "An earlier task to continue here."},
        },
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, conversation_id=None, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(f"Missing permission: {self.required_permission}")
        conversation = await _conversation(db, conversation_id, organization_id, user_id)
        if conversation is None:
            return json.dumps({"updated": False, "error": "No conversation to record a task in."})

        task = await task_memory_service.current(db, conversation)
        resume = kwargs.get("resume_task_id")
        if resume:
            earlier = await task_memory_service.get(db, uuid.UUID(str(resume)), organization_id, user_id)
            task = await task_memory_service.create(
                db, conversation, user_id, title=earlier.title, objective=earlier.objective,
                agent=earlier.agent, connection_id=earlier.connection_id, actor="assistant",
            )
            task.state = {**(earlier.state or {}), "resumed_from": str(earlier.id)}
            task.work_item_id = earlier.work_item_id
            await db.flush()
        elif kwargs.get("start_new_task") or task is None:
            title = str(kwargs.get("title") or "").strip()
            if not title:
                return json.dumps({"updated": False, "error": "A new task needs a title."})
            task = await task_memory_service.create(
                db, conversation, user_id, title=title, objective=kwargs.get("objective"),
                agent=None, connection_id=task.connection_id if task else None, actor="assistant",
            )
            kwargs.pop("title", None)
            kwargs.pop("objective", None)

        task = await task_memory_service.apply_update(
            db, task, user_id, actor="assistant",
            finding=kwargs.get("finding"), decision=kwargs.get("decision"), blocker=kwargs.get("blocker"),
            next_step=kwargs.get("next_step"), status=kwargs.get("status"),
            title=kwargs.get("title"), objective=kwargs.get("objective"),
        )
        return json.dumps({"updated": True, "task": {"id": str(task.id), "title": task.title,
                                                     "status": task.status}})


class SearchTaskMemoryTool(Tool):

    name = "search_task_memory"
    needs_conversation = True
    description = (
        "Find the user's earlier tasks — by words in the title or objective, a TM1 object they "
        "touched, or status — with what each found, decided and changed. Use when the user asks "
        "to continue or recall earlier work (\"continue the Actual Allocation investigation\", "
        "\"what did we change last week?\"). Summarize from what is returned; if nothing matches, "
        "say so rather than reconstructing it. Only the user's own tasks on connections they can "
        "still use are returned."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "object_name": {"type": "string"},
            "status": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        },
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, conversation_id=None, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(f"Missing permission: {self.required_permission}")
        tasks = await task_memory_service.search(
            db, organization_id, user_id, query=kwargs.get("query"), object_name=kwargs.get("object_name"),
            status=kwargs.get("status"), limit=int(kwargs.get("limit") or 5),
        )
        return json.dumps({
            "tasks": [
                {
                    "id": str(t.id), "title": t.title, "status": t.status, "updated_at": t.updated_at,
                    "this_conversation": str(t.conversation_id) == str(conversation_id),
                    "conversation_id": str(t.conversation_id),
                    "objects": (t.state or {}).get("objects", [])[-8:],
                    "findings": [f["text"] for f in (t.state or {}).get("findings", [])[-3:]],
                    "decisions": [d["text"] for d in (t.state or {}).get("decisions", [])[-3:]],
                    "changes": (t.state or {}).get("actions", [])[-5:],
                    "next_step": (t.state or {}).get("next_step"),
                }
                for t in tasks
            ],
            "evidence": "The user's task memory, as recorded; changes show the status stored at the last turn.",
        }, default=str)
