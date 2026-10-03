"""Read TM1 server and process logs.

Logs are unbounded and a busy server produces thousands of lines an hour, so
every function here takes a hard row cap and every content read is truncated.
Without that, one broad call fills the model's context window and the
conversation is over.
"""

import re
import uuid
from datetime import datetime

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

# A single tool call must never return more than this, whatever it asks for.
MAX_ROWS = 200
DEFAULT_ROWS = 50

# A process error log is a file; cap what we feed the model.
MAX_LOG_CHARS = 20000

# TM1 writes error locations as, for example:
#   Error: Prolog procedure line (12): Invalid key: ...
# The section name and line number are what let us resolve it back to code.
_ERROR_LOCATION = re.compile(
    r"\b(Prolog|Metadata|Data|Epilog)\s+procedure\s+line\s*\((\d+)\)\s*:?\s*(.*)",
    re.IGNORECASE,
)


def clamp(top: int | None) -> int:
    if not top or top < 1:
        return DEFAULT_ROWS
    return min(int(top), MAX_ROWS)


def truncate_log(text: str, limit: int = MAX_LOG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated - log is {len(text)} characters]"


def parse_error_locations(log_text: str) -> list[dict]:
    """Pull (section, line, message) out of a TM1 process error log.

    Returns an empty list when the log has no recognisable location - an
    aborted process often logs only a ProcessQuit with no line reference, and
    that is a normal outcome rather than a failure to parse.
    """

    found = []
    for match in _ERROR_LOCATION.finditer(log_text):
        section, line, message = match.group(1), match.group(2), match.group(3)
        found.append(
            {
                "section": section.lower(),
                "line_number": int(line),
                "message": message.strip(),
            }
        )
    return found


async def get_message_log(
    client: TM1Service,
    connection_id: uuid.UUID,
    top: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    level: str | None = None,
    logger: str | None = None,
    contains: list[str] | None = None,
    **resilience_kwargs,
) -> list[dict]:
    entries = await call_with_resilience(
        connection_id,
        client.server.get_message_log_entries,
        reverse=True,
        since=since,
        until=until,
        top=clamp(top),
        level=level,
        logger=logger,
        # Filtered on the server: a busy log holds thousands of lines and
        # only the ones naming this process matter.
        msg_contains=contains or None,
        **resilience_kwargs,
    )
    return [dict(entry) for entry in (entries or [])]


async def get_transaction_log(
    client: TM1Service,
    connection_id: uuid.UUID,
    cube: str | None = None,
    user: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    top: int | None = None,
    **resilience_kwargs,
) -> list[dict]:
    entries = await call_with_resilience(
        connection_id,
        client.server.get_transaction_log_entries,
        reverse=True,
        cube=cube,
        user=user,
        since=since,
        until=until,
        top=clamp(top),
        **resilience_kwargs,
    )
    return [dict(entry) for entry in (entries or [])]


async def list_process_error_logs(
    client: TM1Service,
    connection_id: uuid.UUID,
    process_name: str | None = None,
    top: int | None = None,
    **resilience_kwargs,
) -> list[str]:
    return await call_with_resilience(
        connection_id,
        client.processes.get_error_log_filenames,
        process_name=process_name,
        top=clamp(top),
        descending=True,
        **resilience_kwargs,
    ) or []


async def get_process_error_log(
    client: TM1Service,
    connection_id: uuid.UUID,
    file_name: str,
    **resilience_kwargs,
) -> str:
    content = await call_with_resilience(
        connection_id,
        client.processes.get_error_log_file_content,
        file_name=file_name,
        **resilience_kwargs,
    )
    return content or ""


# TM1.Process message-log lines, as TM1 11 and 12 write them. Each pattern
# is matched against TM1's own text; a line that matches none is kept with
# outcome "other" rather than guessed at.
_RUN_ELAPSED = re.compile(r"elapsed time\s+([0-9]+(?:\.[0-9]+)?)\s*seconds", re.IGNORECASE)
_RUN_ERROR_FILE = re.compile(r"(TM1ProcessError_[^\s\"']+\.log)", re.IGNORECASE)


def classify_run_message(message: str) -> str:
    text = message.lower()

    if "finished executing normally" in text:
        return "succeeded"
    if "aborted" in text:
        return "aborted"
    if "minor errors" in text or "with errors" in text:
        return "completed_with_errors"
    if "processquit" in text or "quit called" in text or "process quit" in text:
        return "quit"
    if "executed by" in text or "started" in text:
        return "started"
    return "other"


def parse_process_runs(entries: list[dict], process_name: str) -> list[dict]:
    """Message-log entries about one process, newest first, each with the
    outcome TM1's own wording states."""

    # TM1 quotes the process name in these lines. Matching the quoted form
    # keeps zLoadAll's runs out of zLoad's history.
    needle = f'"{process_name}"'.lower()
    runs = []

    for entry in entries:
        message = str(entry.get("Message") or "")

        if needle not in message.lower():
            continue

        elapsed = _RUN_ELAPSED.search(message)
        error_file = _RUN_ERROR_FILE.search(message)
        runs.append(
            {
                "timestamp": str(entry.get("TimeStamp") or ""),
                "level": entry.get("Level"),
                "outcome": classify_run_message(message),
                "elapsed_seconds": float(elapsed.group(1)) if elapsed else None,
                "error_log_file": error_file.group(1) if error_file else None,
                "message": message[:400],
            }
        )

    return runs
