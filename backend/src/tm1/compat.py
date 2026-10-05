"""What older TM1 servers do differently.

Found by running tests/live/test_write_paths.py against TM1 11.0.1
(Planning Sample) on 2026-10-05. Every path tries the modern REST call
first; these recognise the specific answers an older server gives, so the
caller can fall back instead of failing:

* `tm1.ExecuteWithReturn` and `tm1.CheckRules` do not exist: the server
  answers 404 with code 278, "'tm1.X' resource can not be resolved".
* `Cube::Update` (writing cells) takes every value as text: a number is
  refused with "Expecting type \\"String\\" but was \\"Numeric\\"".
* `tm1.Execute` answers 204 on success and, for a failing process, raises
  with the outcome ("ProcessAborted") and TM1's error line in its details.
"""

import json
import re

from TM1py.Exceptions import TM1pyRestException


def _text(exc: Exception) -> str:
    return getattr(exc, "message", None) or str(exc)


def is_unsupported_action(exc: Exception, action: str) -> bool:
    """The server has no `tm1.<action>` REST action."""

    return (
        isinstance(exc, TM1pyRestException)
        and exc.status_code == 404
        and f"tm1.{action}" in _text(exc)
        and "can not be resolved" in _text(exc)
    )


def wants_text_values(exc: Exception) -> bool:
    """A cell write refused because this server takes values as text."""

    text = _text(exc)
    return isinstance(exc, TM1pyRestException) and "Cube::Update" in text and "String" in text and "Numeric" in text


def as_text(value) -> str:
    """A number as TM1 reads it back: 5 not 5.0, no exponent for ordinary values."""

    if isinstance(value, str):
        return value
    return format(value, ".15g")


_OUTCOMES = {
    "ProcessAborted": "Aborted",
    "ProcessCompletedWithMessages": "CompletedWithMessages",
    "ProcessQuit": "QuitCalled",
}


def run_outcome(exc: Exception) -> tuple[str, str | None] | None:
    """For `tm1.Execute`: the outcome of a run that did not complete
    cleanly, and TM1's error text — or None if this is not a run outcome
    (a real failure to call the server, which the caller re-raises)."""

    if not isinstance(exc, TM1pyRestException):
        return None
    text = _text(exc)
    try:
        error = json.loads(text).get("error", {})
    except (ValueError, AttributeError):
        match = re.search(r'"message"\s*:\s*"(Process\w+)"', text)
        error = {"message": match.group(1)} if match else {}
    status = _OUTCOMES.get(str(error.get("message", "")))
    if status is None:
        return None
    details = error.get("details") or {}
    detail = " ".join(str(v) for v in details.values()) if isinstance(details, dict) else str(details)
    return status, detail.replace("﻿", "").strip() or None
