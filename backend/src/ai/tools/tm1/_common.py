"""Shared plumbing for TM1 tools.

`TM1Tool` is the permission check every tool repeats, written once, and
`evidence()` is the block every investigative tool returns so the model
can say which parts of its answer were read from TM1, which were derived
by analysis, and which could not be known.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException, ValidationException
from src.repositories.auth_repository import auth_repository

CONNECTION_ID_SCHEMA = {
    "type": "string",
    "description": "The ID of the TM1 connection to query.",
}

_DENIED = {
    "tm1.read": "You do not have permission to read TM1 data.",
    "tm1.write": "You do not have permission to draft TM1 changes.",
    "tm1.execute": "You do not have permission to run TM1 processes.",
}


class TM1Tool(Tool):

    required_permission = "tm1.read"

    async def _authorize(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                _DENIED.get(
                    self.required_permission,
                    f"Missing permission: {self.required_permission}",
                )
            )


def connection_id_of(kwargs: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(kwargs["connection_id"]))
    except (KeyError, ValueError) as exc:
        raise ValidationException("connection_id must be a connection UUID.") from exc


def required_text(kwargs: dict, key: str) -> str:
    value = str(kwargs.get(key) or "").strip()

    if not value:
        raise ValidationException(f"{key} is required.")

    return value


def evidence(
    verified: list[str] | None = None,
    inferred: list[str] | None = None,
    unknown: list[str] | None = None,
) -> dict:
    """VERIFIED: read from TM1 in this call, or derived from it by a parser.
    INFERRED: a conclusion drawn from verified facts that TM1 did not state.
    UNKNOWN: what TM1 does not expose, or what could not be resolved.

    Tools fill all three honestly; the model is instructed to keep the same
    distinction in its answer.
    """

    return {
        "verified": verified or [],
        "inferred": inferred or [],
        "unknown": unknown or [],
    }
