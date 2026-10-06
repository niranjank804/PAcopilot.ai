"""Record every API request a person makes (see models/request_log.py).

The row is written after the response has been sent, as a background task
on that response, so the person never waits for it; a failure to write is
logged and never turns into a failed request. Only the caller's identity
is read from the bearer token — the token itself, request bodies and
anything else that could hold a secret are never stored.

Machine traffic is left out: the TM1 gateway's long polls, report
workers, the cron, health checks and CORS preflights. They are not people,
and the gateway alone would outnumber every user many times over.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

from loguru import logger
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.rate_limit import client_ip_of
from src.middleware.request_context import current_request_id

SKIPPED_PREFIXES = ("/gateway/", "/worker/", "/internal/", "/health", "/docs", "/openapi", "/redoc", "/favicon")


# No endpoint takes a secret in its query string today; redacting these
# keys anyway keeps a future one (or a client mistake) out of the log.
SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "refresh_token", "id_token", "code", "api_key", "apikey",
    "key", "password", "secret", "signature", "state",
}


def _safe_query(query: str) -> str:
    from urllib.parse import parse_qsl, urlencode

    return urlencode([
        (k, "[REDACTED]" if k.lower() in SENSITIVE_QUERY_KEYS else v)
        for k, v in parse_qsl(query, keep_blank_values=True)
    ])


def _user_id(authorization: str | None) -> uuid.UUID | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        from src.services.jwt_service import jwt_service

        return uuid.UUID(jwt_service.decode_token(authorization[7:].strip())["sub"])
    except Exception:
        # An invalid or expired token: the request is still recorded, with
        # no person, and the API itself answers 401.
        return None


def _connection_id(request) -> uuid.UUID | None:
    value = request.path_params.get("connection_id") or request.query_params.get("connection_id")
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def write_request_log(entry: dict) -> None:
    """Insert one row in its own session. Replaced in tests."""

    from src.database.models.request_log import RequestLog
    from src.database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(RequestLog(**entry))
        await session.commit()


async def _safely(writer: Callable[[dict], Awaitable[None]], entry: dict) -> None:
    try:
        await writer(entry)
    except Exception as exc:
        logger.warning("Request log not written: {}", type(exc).__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path == "/" or path.startswith(SKIPPED_PREFIXES):
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)

        route = request.scope.get("route")
        query = request.url.query
        entry = {
            "user_id": _user_id(request.headers.get("authorization")),
            "method": request.method[:10],
            "path": (f"{path}?{_safe_query(query)}" if query else path)[:500],
            "route": getattr(route, "path", None),
            "status_code": response.status_code,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "connection_id": _connection_id(request),
            "ip_address": (client_ip_of(request) or "")[:45] or None,
            "user_agent": (request.headers.get("user-agent") or "")[:500] or None,
            "request_id": current_request_id(),
        }

        # Imported here so tests can replace the writer on this module.
        from src.middleware import request_log as module

        task = BackgroundTask(_safely, module.write_request_log, entry)
        if response.background is None:
            response.background = task
        else:
            earlier = response.background

            async def both() -> None:
                await earlier()
                await task()

            response.background = BackgroundTask(both)
        return response
