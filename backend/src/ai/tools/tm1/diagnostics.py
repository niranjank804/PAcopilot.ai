"""Process execution history and failure diagnosis.

`diagnose_process_failure` is the whole "why did process X fail?" workflow
in one call, so the answer does not depend on the model remembering to
look in four places:

1. the process source (what the code does, what it writes and calls)
2. the newest error log for it, with each logged error resolved to the
   exact code line
3. the message-log lines TM1 wrote about its runs
4. static review errors in the current code

Each part is labelled by what it is. What TM1 said is VERIFIED. The cause
is not decided here — that is the model's INFERENCE, and the instructions
say to present it as such. Anything that could not be read is UNKNOWN,
with the reason.

Nothing here runs a process. To re-run after a fix, the model proposes a
run (`propose_process_run`) and a person approves it.
"""

import json
import re
from datetime import datetime

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
        "current code. Every item is marked verified (read from TM1) or "
        "unknown (not available, with why). Use this first for any 'why did "
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

        # 2. The error log, mapped to code.
        error_log: dict | None = None
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
                "recent_runs": runs[:10],
                "code_errors": code_errors,
                "evidence": evidence(
                    verified=verified,
                    inferred=[
                        "The cause of the failure is not stated by TM1. Explain "
                        "it as an inference from the error log and code above"
                    ],
                    unknown=unknown,
                ),
            },
            default=str,
        )
