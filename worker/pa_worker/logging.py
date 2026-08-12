"""Structured, redacting logs.

Two responsibilities:

1. **Correlation.** Every line emitted while a job is in flight carries
   correlation_id / execution_id / report_id / organization_id / worker_id,
   so one report run can be followed from the API call through the Excel
   session and back without grepping timestamps.

2. **Redaction.** This process handles a worker credential, a bearer
   token, and — depending on the customer's configuration — a TM1
   password. `redact()` is applied to every message and to every
   diagnostics blob that leaves the process. It is a backstop, not a
   licence: nothing should be *passing* a secret to the logger in the
   first place.
"""

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

# Redaction patterns. Ordered most-specific first so a bearer token is
# matched as a token rather than by the generic key=value rule.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Our own credential prefixes — see backend worker_credentials.py.
    (re.compile(r"pacw-(?:enroll|secret)-[A-Za-z0-9_\-]+"), "<redacted-credential>"),
    # Authorization headers and bearer tokens in any casing.
    (
        re.compile(r"(?i)\b(authorization|bearer)\b[:=\s]+\S+"),
        r"\1 <redacted>",
    ),
    # JWTs, wherever they appear.
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "<redacted-token>",
    ),
    # Anything self-describing as a secret in a key=value or key: value.
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_\-]?key|credential)"
            r"\b\s*[:=]\s*(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1=<redacted>",
    ),
)

_context: ContextVar[dict[str, Any]] = ContextVar("pa_worker_context", default={})

# Keys whose *value* is a secret regardless of what the value looks like.
# The regex patterns above only fire on inline "key=value" text, which
# does not cover a structured payload — in a dict, the key and the value
# are separate strings, so `{"password": "hunter2"}` has nothing for a
# key=value pattern to match and the secret would pass straight through.
# Diagnostics blobs are dicts, so this is the common case, not the
# exotic one.
_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|api[_\-]?key|credential|authorization)"
)

_REDACTED = "<redacted>"


def redact(value: Any) -> Any:
    """Strip anything that looks like a credential.

    Recurses through dicts and lists so a diagnostics blob is covered as
    thoroughly as a message string, and redacts by key name as well as by
    value shape.
    """

    if isinstance(value, str):
        result = value

        for pattern, replacement in _PATTERNS:
            result = pattern.sub(replacement, result)

        return result

    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and _SENSITIVE_KEY.search(key)
                else redact(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return type(value)(redact(item) for item in value)

    return value


def set_context(**fields: Any) -> None:
    """Attach correlation fields to every subsequent line on this task."""

    merged = dict(_context.get())
    merged.update({key: value for key, value in fields.items() if value is not None})
    _context.set(merged)


def clear_context() -> None:
    _context.set({})


def get_context() -> dict[str, Any]:
    return dict(_context.get())


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _context.get()

        record.context = (
            " ".join(f"{key}={value}" for key, value in context.items())
            if context
            else "-"
        )

        # Redaction happens here rather than at each call site so it
        # cannot be forgotten by one of them.
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)

        return True


_configured = False


def configure(level: str = "INFO", log_file: str | None = None) -> None:
    """Idempotent — safe to call from the CLI and from a child process."""

    global _configured

    if _configured:
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(context)s | %(message)s"
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    root = logging.getLogger("pa_worker")
    root.setLevel(level.upper())
    root.propagate = False

    context_filter = _ContextFilter()

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pa_worker.{name}")
