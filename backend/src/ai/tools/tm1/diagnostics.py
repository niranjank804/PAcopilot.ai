"""Process execution history and failure diagnosis.

`diagnose_process_failure` is the whole "why did process X fail?" workflow
in one call, so the answer does not depend on the model remembering to
look in four places:

1. the process source (what the code does, what it writes and calls)
2. the newest error log for it, with each logged error resolved to the
   exact code line
3. the message-log lines TM1 wrote about its runs
4. static review errors in the current code
5. each logged error classified, and its claim checked against the model
   now (src/tm1/diagnostics/failure.py)
6. what runs the process, and what changed around it lately
   (src/tm1/diagnostics/context.py)

Each part is labelled by what it is. What TM1 said is VERIFIED. The cause
is not decided here — that is the model's INFERENCE, and the instructions
say to present it as such. Anything that could not be read is UNKNOWN,
with the reason.

Nothing here runs a process. To re-run after a fix, the model proposes a
run (`propose_process_run`) and a person approves it.
"""

import json
import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.tm1._common import (
    CONNECTION_ID_SCHEMA,
    TM1Tool,
    connection_id_of,
    evidence,
    required_text,
)
from src.ai.tools.tm1.explore import record_from, references_of
from src.ai.tools.tm1.logs import resolve_locations
from src.database.models.tm1_change import TM1Change
from src.tm1.diagnostics import context as failure_context
from src.tm1.diagnostics.failure import findings_from_log, verify
from src.tm1.service import tm1_integration_service
from src.tm1.services import log_service, process_service
from src.tm1.ti.review import review

HISTORY_ROWS = 50
MESSAGE_LOG_LOGGER = "TM1.Process"
_FILE_TIMESTAMP = re.compile(r"(\d{14})")


def _file_time(file_name: str) -> str | None:
    """TM1 stamps error-log names with the run's start, YYYYMMDDhhmmss."""

    match = _FILE_TIMESTAMP.search(file_name or "")

    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


class GetProcessExecutionHistoryTool(TM1Tool):

    name = "get_process_execution_history"
    description = (
        "List a process's recent runs as the TM1 message log recorded them, "
        "newest first: when, the outcome in TM1's own words (finished "
        "normally, aborted, completed with errors, quit), elapsed time and "
        "the error-log file where TM1 wrote one. Use this for 'did X run "
        "last night', 'when did it last succeed', 'how long does it take'. "
        "Only as far back as the server's message log retains."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {"type": "string", "description": "The process."},
            "top": {
                "type": "integer",
                "description": f"Message-log lines to scan (default and max {HISTORY_ROWS}).",
            },
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        name = required_text(kwargs, "process_name")

        entries = await tm1_integration_service.run(
            db,
            connection_id_of(kwargs),
            organization_id,
            log_service.get_message_log,
            top=min(int(kwargs.get("top") or HISTORY_ROWS), HISTORY_ROWS),
            logger=MESSAGE_LOG_LOGGER,
            contains=[name],
        )
        runs = log_service.parse_process_runs(entries, name)
        finished = [r for r in runs if r["outcome"] != "started" and r["outcome"] != "other"]

        return json.dumps(
            {
                "process": name,
                "runs": runs,
                "last_outcome": finished[0]["outcome"] if finished else None,
                "last_finished_at": finished[0]["timestamp"] if finished else None,
                "evidence": evidence(
                    verified=["TM1 message log, logger TM1.Process, filtered on the server by process name"],
                    inferred=["'outcome' classifies TM1's wording; the original line is in 'message'"],
                    unknown=(
                        []
                        if runs
                        else [
                            "No run of this process in the retained message log. "
                            "Either it has not run recently, or the log has rolled over."
                        ]
                    )
                    + [
                        "TM1 REST has no per-process statistics entity; elapsed "
                        "time exists only where TM1 wrote it into the log"
                    ],
                ),
            }
        )


class DiagnoseProcessFailureTool(TM1Tool):

    name = "diagnose_process_failure"
    description = (
        "Investigate why a TurboIntegrator process failed, in one call: its "
        "source and what it writes and calls, its newest error log with "
        "each error resolved to the exact code line, the message-log lines "
        "TM1 wrote about its runs, and errors a static review finds in the "
        "current code. Each logged error is classified (element not found, "
        "missing object, conversion, data source, consolidated or rule cell, "
        "security or lock, MDX, ProcessQuit) and its claim checked against "
        "the model now (is the element there yet?). Also returns what runs "
        "the process, objects it uses that disappeared in recent extractions, "
        "and changes made to it through PA-Copilot. Every item is marked "
        "verified (read from TM1) or unknown (not available, with why). Use "
        "this first for any 'why did "
        "X fail / abort / not load' question, then explain the cause as an "
        "inference from this evidence and, if a fix is needed, draft it with "
        "propose_process_update."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {"type": "string", "description": "The process that failed."},
            "error_log_file": {
                "type": "string",
                "description": "A specific error-log file. Default: the newest one for this process.",
            },
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        name = required_text(kwargs, "process_name")
        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )
        cid = connection.id
        verified: list[str] = []
        unknown: list[str] = []

        # 1. The process itself. Not found is a real answer: raise it.
        process = await process_service.get_process(client, cid, name)
        verified.append("Process source read live from TM1 REST")
        record = record_from(process)
        refs = references_of(record)

        # 2. The error log, mapped to code, and what kind of failure it is.
        error_log: dict | None = None
        failures = []
        unclassified: list[str] = []
        file_name = kwargs.get("error_log_file")

        try:
            if not file_name:
                files = await log_service.list_process_error_logs(
                    client, cid, process_name=process.name, top=5
                )
                file_name = files[0] if files else None

            if file_name:
                content = await log_service.get_process_error_log(client, cid, str(file_name))
                locations = log_service.parse_error_locations(content)
                error_log = {
                    "file": file_name,
                    "run_started": _file_time(str(file_name)),
                    "errors": resolve_locations(locations, process) if locations else [],
                    "excerpt": log_service.truncate_log(content, 4000),
                }
                verified.append(f"Error log {file_name} read from TM1")
                failures, unclassified = findings_from_log(locations, content)

                if not locations:
                    unknown.append(
                        "The error log names no code line (common for ProcessQuit "
                        "or a datasource failure); see the excerpt"
                    )
            else:
                unknown.append(
                    "No error log exists for this process. TM1 writes one only "
                    "when a run records errors; a run that quit cleanly or was "
                    "never started leaves none"
                )
        except Exception as exc:  # noqa: BLE001 - one missing source must not end the diagnosis
            unknown.append(f"Error logs could not be read ({type(exc).__name__})")

        # 3. What the message log says about its runs.
        runs: list[dict] = []

        try:
            entries = await log_service.get_message_log(
                client, cid, top=HISTORY_ROWS, logger=MESSAGE_LOG_LOGGER, contains=[process.name]
            )
            runs = log_service.parse_process_runs(entries, process.name)
            verified.append("TM1 message log (TM1.Process) read")

            if not runs:
                unknown.append("No run of this process in the retained message log")
        except Exception as exc:  # noqa: BLE001
            unknown.append(f"Message log could not be read ({type(exc).__name__})")

        # 4. What a static review of the current code finds.
        findings, _ = review(record)
        code_errors = [f.to_dict() for f in findings if f.severity == "error"]

        if code_errors:
            verified.append("Static review of the current source (deterministic)")

        # 5. Each failure's claim checked against the model as it is now.
        if failures:
            await verify(client, cid, failures)
            if any(f.checks for f in failures):
                verified.append("Objects named in the error log checked against TM1 now")

        # 6. What runs it, and what changed around it lately.
        touched = {process.name} | {
            entry["name"]
            for kind in ("cube", "dimension", "process", "view", "subset")
            for entry in refs["objects"].get(kind, [])
        }
        run_by = await failure_context.runners(db, connection.id, organization_id, process.name)
        model_changes = await failure_context.model_changes_touching(
            db, connection.id, organization_id, touched
        )
        own_changes = await failure_context.recent_changes(
            db, connection.id, organization_id, process.name
        )

        if run_by is None:
            unknown.append(
                "What runs this process: it is not in the dependency map (run "
                "metadata extraction)"
            )
        if own_changes:
            verified.append("PA-Copilot change records for this process")

        unresolved = refs["unresolved"]

        if unresolved:
            unknown.append(
                f"{len(unresolved)} object reference(s) are built from variables; "
                "which object they hit depends on the run's parameters"
            )

        unknown.append(
            "The source data the run read (file contents, view values) is not "
            "read by this tool"
        )

        return json.dumps(
            {
                "process": process.name,
                "parameters": process.parameters,
                "datasource": {"type": process.datasource_type, "name": process.datasource_name},
                "writes_cubes": sorted(record.cubes_written),
                "reads_cubes": sorted(record.cubes_read),
                "calls_processes": sorted(record.processes_called),
                "error_log": error_log,
                # What kind of failure each error is (a reading of TM1's
                # words: inferred), with live checks of its claim (verified).
                "failures": [f.to_dict() for f in failures],
                "unclassified_errors": unclassified,
                "context": {
                    "run_by": run_by,
                    "model_changes_affecting_it": model_changes,
                    "recent_changes_through_pa_copilot": own_changes,
                },
                "recent_runs": runs[:10],
                "code_errors": code_errors,
                "evidence": evidence(
                    verified=verified,
                    inferred=[
                        "The cause of the failure is not stated by TM1. Explain "
                        "it as an inference from the error log and code above",
                        *(
                            ["Each failure's category is a reading of TM1's error "
                             "text; its checks are verified"]
                            if failures
                            else []
                        ),
                    ],
                    unknown=unknown,
                ),
            },
            default=str,
        )


class GetChangeStatusTool(TM1Tool):

    name = "get_change_status"
    description = (
        "What happened to changes proposed through PA-Copilot: whether a "
        "draft is still waiting for approval, was applied, failed, was "
        "rejected or rolled back, and for a process run what TM1 reported "
        "(success, status, error log). Use it after proposing a fix or a "
        "run, when the user says they approved it, to verify the outcome "
        "instead of assuming it. Give change_id, or target_name for the "
        "newest changes to that object."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "change_id": {"type": "string", "description": "A change's id, from the proposal."},
            "target_name": {
                "type": "string",
                "description": "A process or cube name: its newest changes (up to 5).",
            },
        },
        "required": ["connection_id"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        connection = await tm1_integration_service.get_connection(
            db, connection_id_of(kwargs), organization_id
        )
        query = select(TM1Change).where(
            TM1Change.connection_id == connection.id,
            TM1Change.organization_id == organization_id,
        )

        change_id = kwargs.get("change_id")
        target = (kwargs.get("target_name") or "").strip()

        if change_id:
            try:
                query = query.where(TM1Change.id == uuid.UUID(str(change_id)))
            except ValueError:
                return json.dumps({"error": f"'{change_id}' is not a change id."})
        elif target:
            query = query.where(func.lower(TM1Change.target_name) == target.lower())
        else:
            return json.dumps({"error": "Give change_id or target_name."})

        changes = (
            await db.execute(query.order_by(TM1Change.created_at.desc()).limit(5))
        ).scalars().all()

        return json.dumps(
            {
                "changes": [
                    {
                        "change_id": str(c.id),
                        "type": c.change_type,
                        "target": c.target_name,
                        "status": c.status,
                        "created_at": c.created_at,
                        "executed_at": c.executed_at,
                        "rolled_back_at": c.rolled_back_at,
                        "error_message": c.error_message,
                        "validation_errors": c.validation_errors,
                        "execution_result": c.execution_result,
                    }
                    for c in changes
                ],
                "evidence": evidence(
                    verified=["PA-Copilot's change records (status as recorded at approval)"],
                    unknown=(
                        ["No change matches; it may not have been proposed through PA-Copilot"]
                        if not changes
                        else []
                    ),
                ),
            },
            default=str,
        )
