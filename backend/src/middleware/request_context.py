"""Per-request correlation id.

Logs were previously untraceable: a single user action fans out into an
agent turn with several tool calls, each logging independently, and
nothing tied those lines back to the request that caused them. With two
gunicorn workers interleaving output there was no way to reconstruct one
request's story from the log.

A context variable rather than a parameter threaded through every call:
the id has to be reachable from deep inside services and repositories
that have no business taking a request object.
"""

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Read by src.core.logging's patcher on every log record.
request_id_var: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

REQUEST_ID_HEADER = "X-Request-ID"


def current_request_id() -> str | None:
    return request_id_var.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign (or adopt) a request id and echo it back to the caller."""

    def __init__(self, app: ASGIApp, *, trust_inbound: bool = False):
        super().__init__(app)

        # An inbound id is only trustworthy behind a gateway that sets it.
        # Adopting a caller-supplied value on a public endpoint lets a
        # client collide ids with someone else's request and poison the
        # log trail, so this defaults off.
        self._trust_inbound = trust_inbound

    async def dispatch(self, request, call_next):
        inbound = (
            request.headers.get(REQUEST_ID_HEADER)
            if self._trust_inbound
            else None
        )

        # Cap the adopted value: it lands in every log line for this
        # request, so an unbounded header would be a log-flooding vector.
        request_id = (inbound or "")[:64].strip() or uuid.uuid4().hex

        token = request_id_var.set(request_id)

        try:
            response = await call_next(request)
        finally:
            # Reset on the way out so the value cannot leak into whatever
            # this worker task handles next.
            request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id

        return response
