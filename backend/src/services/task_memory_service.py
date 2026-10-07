"""Task memory (models.ai_task): the working state of one engineering job.

How it is kept current, without the user saving anything:

* A tool-using turn with no open task starts one, titled from the request.
  Later turns in the conversation continue it — "check the rules too",
  "okay, fix it" — until the user starts a new task or the assistant does
  so because the objective clearly changed (update_task_memory).
* Every tool the assistant runs adds the TM1 objects it named; a drafted
  change is added as a proposed action, and the task waits for approval.
  Each turn reads the change's status back, so "what did we change?"
  answers from the record, not from recollection.
* Findings, decisions and the next step are written by the assistant with
  update_task_memory, attributed, and kept as append-only events.

What the assistant is given each turn is bounded (prompt_block): the newest
items of each kind, cut short. The full history stays in ai_task_events,
ai_tool_executions and the audit log.

Access: a task belongs to the person whose conversation it is, within the
organization, and is shown only while they may still use its TM1
connection. Nothing here ever becomes engineering memory by itself.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_task import AITask, AITaskEvent
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_connection import TM1Connection
from src.database.models.work_item import WorkItem
from src.services.audit_service import audit_service

STATUSES = (
    "active", "waiting_for_user", "waiting_for_approval", "blocked",
    "completed", "failed", "cancelled", "archived",
)
OPEN = ("active", "waiting_for_user", "waiting_for_approval", "blocked")
# Statuses a person or the assistant may set directly; waiting_for_approval
# follows from drafted changes, not from a claim.
SETTABLE = ("active", "waiting_for_user", "blocked", "completed", "failed", "cancelled", "archived")

OBJECT_KEYS = {
    "cube_name": "cubes", "source_cube": "cubes", "target_cube": "cubes",
    "dimension_name": "dimensions", "hierarchy_name": "dimensions",
    "process_name": "processes", "source_process": "processes", "new_process_name": "processes",
    "chore_name": "chores", "view_name": "views", "subset_name": "subsets",
}
KEEP = {"objects": 15, "findings": 25, "decisions": 15, "actions": 25, "blockers": 10}
IN_PROMPT = {"objects": 10, "findings": 8, "decisions": 5, "actions": 8, "blockers": 3}
TEXT_LIMIT = 400
NEW_TASK = re.compile(r"^\s*(?:new task|start (?:a )?new task)\b[\s:,.-]*", re.IGNORECASE)
# Tools whose results are task memory itself, not evidence for it.
SELF_TOOLS = {"update_task_memory", "search_task_memory"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cut(text, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _title_from(message: str) -> str:
    line = NEW_TASK.sub("", (message or "").strip()).splitlines()[0] if message and message.strip() else ""
    return _cut(line, 120) or "Untitled task"


class TaskMemoryService:

    # ------------------------------------------------------------ access

    async def _may_see(self, db: AsyncSession, task: AITask, organization_id, user_id) -> bool:
        if task.organization_id != organization_id or task.user_id != user_id:
            return False
        if task.connection_id is None:
            return True
        from src.tm1.service import tm1_integration_service

        connection = await db.get(TM1Connection, task.connection_id)
        return connection is None or await tm1_integration_service.may_access(db, connection, user_id=user_id)

    async def get(self, db: AsyncSession, task_id: uuid.UUID, organization_id, user_id) -> AITask:
        """A task its owner may still see; anything else is not found."""

        task = await db.get(AITask, task_id)
        if task is None or not await self._may_see(db, task, organization_id, user_id):
            raise NotFoundException("Task not found.")
        return task

    async def _locked(self, db: AsyncSession, task: AITask) -> AITask:
        """The row, locked for this transaction, so two turns updating one
        task apply one after the other instead of the second erasing the
        first."""

        return (await db.execute(
            select(AITask).where(AITask.id == task.id).with_for_update().execution_options(populate_existing=True)
        )).scalar_one()

    # ------------------------------------------------------------ events

    async def _event(self, db, task: AITask, kind: str, data: dict, actor: str, user_id=None) -> None:
        db.add(AITaskEvent(organization_id=task.organization_id, task_id=task.id, kind=kind,
                           data=data, actor=actor, user_id=user_id))

    async def _audit(self, db, task: AITask, user_id, action: str, values: dict) -> None:
        await audit_service.log(db, organization_id=task.organization_id, user_id=user_id, action=action,
                                entity="AITask", entity_id=task.id, new_values=values)

    def _touch(self, task: AITask, state: dict) -> None:
        # A new dict, so SQLAlchemy sees the JSONB change.
        task.state = dict(state)
        task.version = (task.version or 0) + 1

    # ------------------------------------------------------------ lifecycle

    async def create(self, db, conversation: AIConversation, user_id, *, title: str, objective: str | None,
                     agent: str | None, connection_id, actor: str = "user") -> AITask:
        task = AITask(organization_id=conversation.organization_id, user_id=user_id,
                      conversation_id=conversation.id, title=_cut(title, 200), objective=_cut(objective, 2000) or None,
                      agent=agent, connection_id=connection_id, status="active", state={}, version=1,
                      last_turn_at=_now())
        db.add(task)
        await db.flush()
        await self._event(db, task, "created", {"title": task.title, "objective": task.objective}, actor, user_id)
        await self._audit(db, task, user_id, "task_created", {"title": task.title, "conversation": str(conversation.id)})
        return task

    async def current(self, db, conversation: AIConversation) -> AITask | None:
        """The task this conversation is working on: its newest that is not
        archived or cancelled."""

        return (await db.execute(
            select(AITask)
            .where(AITask.conversation_id == conversation.id, AITask.status.not_in(("archived", "cancelled")))
            .order_by(AITask.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    async def begin_turn(self, db, conversation: AIConversation, user_id, message: str, *, agent: str | None,
                         connection_id, tools: bool, new_task: bool = False,
                         task_id: uuid.UUID | None = None) -> AITask | None:
        """The task this turn belongs to, started or resumed as needed."""

        if task_id is not None:
            task = await self.get(db, task_id, conversation.organization_id, user_id)
            if task.conversation_id != conversation.id:
                raise ValidationException("That task belongs to another conversation.")
        elif new_task or NEW_TASK.match(message or ""):
            return await self.create(db, conversation, user_id, title=_title_from(message), objective=message,
                                     agent=agent, connection_id=connection_id)
        else:
            task = await self.current(db, conversation)
            if task is None:
                if not tools:
                    return None
                return await self.create(db, conversation, user_id, title=_title_from(message),
                                         objective=message, agent=agent, connection_id=connection_id)

        task = await self._locked(db, task)
        if task.status in ("waiting_for_user", "blocked"):
            await self._set_status(db, task, "active", "user", user_id, reason="the user continued")
        task.agent = task.agent or agent
        task.connection_id = task.connection_id or connection_id
        task.last_turn_at = _now()
        await db.flush()
        return task

    async def end_turn(self, db, task: AITask | None, user_id, answer: str | None = None) -> None:
        """After the answer: the task waits on the person, or on approval.

        The answer's opening is kept as `last_answer`, marked as such — not
        as a finding. The assistant does not always record its findings with
        update_task_memory (seen live, 2026-10-07), and without this a task
        picked up later in another conversation would have lost what the
        last turn concluded."""

        if task is None:
            return
        task = await self._locked(db, task)
        if answer and answer.strip():
            state = dict(task.state or {})
            state["last_answer"] = {"text": _cut(answer, 600), "at": _now().isoformat()}
            self._touch(task, state)
            await self._event(db, task, "answer", {"text": _cut(answer, 2000)}, "assistant", user_id)
        await self.refresh_actions(db, task, user_id)
        if task.status == "active":
            pending = any(a.get("status") == "draft" for a in task.state.get("actions", []))
            await self._set_status(db, task, "waiting_for_approval" if pending else "waiting_for_user",
                                   "system", user_id)
        await db.flush()

    async def _set_status(self, db, task: AITask, status: str, actor: str, user_id, reason: str | None = None):
        if status not in STATUSES:
            raise ValidationException(f"status must be one of: {', '.join(STATUSES)}.")
        if status == task.status:
            return
        previous = task.status
        task.status = status
        task.version = (task.version or 0) + 1
        await self._event(db, task, "status", {"from": previous, "to": status, "reason": reason}, actor, user_id)
        await self._audit(db, task, user_id, "task_status_changed", {"from": previous, "to": status, "by": actor})

    # ------------------------------------------------------------ evidence

    def _add(self, state: dict, kind: str, item, key=None) -> bool:
        items = list(state.get(kind, []))
        if key is not None and any(key(existing) == key(item) for existing in items):
            return False
        items.append(item)
        state[kind] = items[-KEEP[kind]:]
        return True

    async def record_tool(self, db, task: AITask | None, user_id, *, name: str, arguments: dict | None,
                          result: str | None, ok: bool) -> None:
        """Fold one tool call into the task: the objects it named, a change it
        drafted, a work item it recorded."""

        if task is None or name in SELF_TOOLS:
            return
        import json

        arguments = arguments or {}
        state = dict(task.state or {})
        added_objects = []
        for key, kind in OBJECT_KEYS.items():
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                item = {"type": kind, "name": _cut(value, 120)}
                if self._add(state, "objects", item, key=lambda o: (o["type"], o["name"].lower())):
                    added_objects.append(item)
        target = arguments.get("target_name")
        if isinstance(target, str) and target.strip() and name.startswith("propose_"):
            kind = "cubes" if name in ("propose_rule_update", "propose_cell_write", "propose_view") else "processes"
            item = {"type": kind, "name": _cut(target, 120)}
            if self._add(state, "objects", item, key=lambda o: (o["type"], o["name"].lower())):
                added_objects.append(item)

        parsed = {}
        if ok and result:
            try:
                parsed = json.loads(result) if result.lstrip().startswith("{") else {}
            except ValueError:
                parsed = {}

        action = None
        change_id = parsed.get("draft_change_id") if isinstance(parsed, dict) else None
        if change_id:
            change = await db.get(TM1Change, uuid.UUID(str(change_id))) if _is_uuid(change_id) else None
            action = {
                "change_id": str(change_id),
                "tool": name,
                "change_type": getattr(change, "change_type", None),
                "target": getattr(change, "target_name", None) or arguments.get("cube_name")
                or arguments.get("process_name") or arguments.get("target_name"),
                "status": getattr(change, "status", None) or parsed.get("status") or "draft",
                "at": _now().isoformat(),
            }
            if not self._add(state, "actions", action, key=lambda a: a["change_id"]):
                action = None

        work_item = parsed.get("work_item_id") if isinstance(parsed, dict) else None
        if name in ("save_work_item", "link_change_to_work_item") and not work_item and parsed.get("reference"):
            found = (await db.execute(
                select(WorkItem.id).where(WorkItem.organization_id == task.organization_id,
                                          WorkItem.reference == parsed["reference"])
            )).scalar_one_or_none()
            work_item = str(found) if found else None

        if not (added_objects or action or (work_item and not task.work_item_id)):
            return
        task = await self._locked(db, task)
        merged = dict(task.state or {})
        for item in added_objects:
            self._add(merged, "objects", item, key=lambda o: (o["type"], o["name"].lower()))
        if added_objects:
            await self._event(db, task, "objects", {"added": added_objects, "tool": name}, "assistant", user_id)
        if action:
            self._add(merged, "actions", action, key=lambda a: a["change_id"])
            await self._event(db, task, "action", action, "assistant", user_id)
            await self._audit(db, task, user_id, "task_action_proposed",
                              {"change_id": action["change_id"], "tool": name})
        if work_item and not task.work_item_id and _is_uuid(work_item):
            task.work_item_id = uuid.UUID(str(work_item))
            await self._event(db, task, "linked", {"work_item_id": str(work_item)}, "assistant", user_id)
            await self._audit(db, task, user_id, "task_linked", {"work_item_id": str(work_item)})
        self._touch(task, merged)
        await db.flush()

    async def refresh_actions(self, db, task: AITask, user_id) -> None:
        """Read each drafted change's status back from its record."""

        actions = list((task.state or {}).get("actions", []))
        ids = [uuid.UUID(a["change_id"]) for a in actions if _is_uuid(a.get("change_id"))]
        if not ids:
            return
        rows = {str(c.id): c for c in (await db.execute(select(TM1Change).where(TM1Change.id.in_(ids)))).scalars()}
        changed = []
        for action in actions:
            change = rows.get(action.get("change_id"))
            if change is not None and change.status != action.get("status"):
                changed.append({"change_id": action["change_id"], "from": action.get("status"), "to": change.status})
                action["status"] = change.status
        if not changed:
            return
        state = dict(task.state or {})
        state["actions"] = actions
        self._touch(task, state)
        for entry in changed:
            await self._event(db, task, "action_status", entry, "system", user_id)
        if task.status == "waiting_for_approval" and not any(a.get("status") == "draft" for a in actions):
            await self._set_status(db, task, "active", "system", user_id, reason="drafted changes were decided")

    async def apply_update(self, db, task: AITask, user_id, *, actor: str = "assistant", finding: str | None = None,
                           decision: str | None = None, next_step: str | None = None, blocker: str | None = None,
                           status: str | None = None, title: str | None = None,
                           objective: str | None = None) -> AITask:
        """Add to the task; nothing recorded before is changed or removed."""

        task = await self._locked(db, task)
        state = dict(task.state or {})
        stamp = {"at": _now().isoformat(), "by": actor}
        if finding:
            item = {"text": _cut(finding), **stamp}
            self._add(state, "findings", item)
            await self._event(db, task, "finding", item, actor, user_id)
        if decision:
            item = {"text": _cut(decision), **stamp}
            self._add(state, "decisions", item)
            await self._event(db, task, "decision", item, actor, user_id)
        if blocker:
            item = {"text": _cut(blocker), **stamp}
            self._add(state, "blockers", item)
            await self._event(db, task, "blocker", item, actor, user_id)
        if next_step:
            state["next_step"] = _cut(next_step)
            await self._event(db, task, "next_step", {"text": state["next_step"], **stamp}, actor, user_id)
        if title:
            await self._event(db, task, "title", {"from": task.title, "to": _cut(title, 200)}, actor, user_id)
            task.title = _cut(title, 200)
        if objective:
            await self._event(db, task, "objective", {"from": task.objective, "to": _cut(objective, 2000)},
                              actor, user_id)
            task.objective = _cut(objective, 2000)
        self._touch(task, state)
        if status:
            if status not in SETTABLE:
                raise ValidationException(f"status must be one of: {', '.join(SETTABLE)}.")
            await self._set_status(db, task, status, actor, user_id)
        await db.flush()
        # updated_at is set by the database on flush; read it back now, not
        # lazily later outside the async context.
        await db.refresh(task)
        return task

    # ------------------------------------------------------------ reading

    async def prompt_block(self, db, task: AITask | None) -> str | None:
        """What the assistant is told about the active task: bounded."""

        if task is None:
            return None
        state = task.state or {}
        connection = await db.get(TM1Connection, task.connection_id) if task.connection_id else None
        work_item = await db.get(WorkItem, task.work_item_id) if task.work_item_id else None
        lines = [
            "ACTIVE TASK — the working state of what this conversation is doing. Resolve references such as "
            "\"it\", \"that process\" or \"the change\" against it, and against the conversation. If a reference "
            "could mean more than one thing here, ask which one rather than guessing. This is task memory, not "
            "organization knowledge: never present it as approved engineering memory, and propose an engineering "
            "memory entry (propose_engineering_memory) only when the user asks for something to be remembered "
            "beyond this task. Record new findings, decisions and the next step with update_task_memory.",
            f"Task: {task.title} (status: {task.status.replace('_', ' ')})",
        ]
        if task.objective:
            lines.append(f"Objective: {_cut(task.objective, 300)}")
        if connection is not None:
            lines.append(f"Connection: {connection.name} ({(connection.environment or 'dev').upper()})")
        if task.agent:
            lines.append(f"Agent: {task.agent}")
        if work_item is not None:
            lines.append(f"Work item: {work_item.reference} — {_cut(work_item.title, 120)}")
        objects = state.get("objects", [])[-IN_PROMPT["objects"]:]
        if objects:
            lines.append("Objects in this task: " + "; ".join(f"{o['type'][:-1]} {o['name']}" for o in objects))
        for kind, label in (("findings", "Findings"), ("decisions", "Decisions"), ("blockers", "Blockers")):
            items = state.get(kind, [])[-IN_PROMPT[kind]:]
            if items:
                lines.append(f"{label}:")
                lines += [f"- {item['text']}" for item in items]
        actions = state.get("actions", [])[-IN_PROMPT["actions"]:]
        if actions:
            lines.append("Changes drafted in this task (status read from the change record now):")
            lines += [
                f"- {a.get('change_type') or a.get('tool')} on {a.get('target') or '?'}: {a.get('status')} "
                f"(change {a['change_id']})"
                for a in actions
            ]
        if state.get("next_step"):
            lines.append(f"Next step: {state['next_step']}")
        if state.get("last_answer"):
            lines.append("Your last answer in this task began (a summary of what you said, not a verified "
                         f"finding): {state['last_answer']['text']}")
        return "\n".join(lines)

    def summary(self, task: AITask) -> dict:
        state = task.state or {}
        return {
            "id": str(task.id), "title": task.title, "status": task.status,
            "conversation_id": str(task.conversation_id),
            "work_item_id": str(task.work_item_id) if task.work_item_id else None,
            "connection_id": str(task.connection_id) if task.connection_id else None,
            "agent": task.agent, "objective": task.objective,
            "objects": state.get("objects", []), "findings": state.get("findings", []),
            "decisions": state.get("decisions", []), "actions": state.get("actions", []),
            "blockers": state.get("blockers", []), "next_step": state.get("next_step"),
            "version": task.version, "created_at": task.created_at, "updated_at": task.updated_at,
        }

    async def search(self, db, organization_id, user_id, *, query: str | None = None, status: str | None = None,
                     conversation_id=None, connection_id=None, work_item_id=None, object_name: str | None = None,
                     since_days: int | None = None, limit: int = 20) -> list[AITask]:
        statement = select(AITask).where(AITask.organization_id == organization_id, AITask.user_id == user_id)
        if status:
            statement = statement.where(AITask.status == status)
        if conversation_id:
            statement = statement.where(AITask.conversation_id == conversation_id)
        if connection_id:
            statement = statement.where(AITask.connection_id == connection_id)
        if work_item_id:
            statement = statement.where(AITask.work_item_id == work_item_id)
        if since_days:
            statement = statement.where(AITask.updated_at >= _now() - timedelta(days=since_days))
        if query and query.strip():
            like = f"%{query.strip()}%"
            statement = statement.where(or_(AITask.title.ilike(like), AITask.objective.ilike(like)))
        statement = statement.order_by(AITask.updated_at.desc()).limit(max(1, min(limit, 100)) * 3)
        tasks = []
        for task in (await db.execute(statement)).scalars():
            if object_name and not any(
                object_name.lower() in o.get("name", "").lower() for o in (task.state or {}).get("objects", [])
            ):
                continue
            if await self._may_see(db, task, organization_id, user_id):
                tasks.append(task)
            if len(tasks) >= limit:
                break
        return tasks

    async def events(self, db, task: AITask) -> list[AITaskEvent]:
        return list((await db.execute(
            select(AITaskEvent).where(AITaskEvent.task_id == task.id).order_by(AITaskEvent.created_at)
        )).scalars())


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


task_memory_service = TaskMemoryService()
