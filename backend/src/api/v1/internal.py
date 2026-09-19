"""Endpoints a scheduler calls, never a person.

On Vercel there is no long-lived process to run periodic tasks in, so
the platform's cron calls these instead. Each is guarded by CRON_SECRET,
sent as a bearer token; without it the endpoint answers 401 to everyone,
including when the secret is simply not configured.
"""

import hmac

from fastapi import APIRouter, Request

from src.core.config import settings
from src.core.exceptions import AuthenticationException
from src.reports.tasks import reap_stale_executions
from src.schemas.response import ApiResponse

router = APIRouter(
    prefix="/internal/cron", tags=["Internal"], include_in_schema=False
)


def _require_cron_secret(request: Request) -> None:
    expected = settings.CRON_SECRET
    supplied = request.headers.get("authorization", "")

    if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise AuthenticationException("Not authorized.")


@router.get("/reap-executions", response_model=ApiResponse[dict])
async def reap_executions(request: Request):
    """Reclaim report executions whose worker stopped heartbeating."""

    _require_cron_secret(request)

    reaped = await reap_stale_executions()

    return ApiResponse(success=True, data={"reaped": reaped})
