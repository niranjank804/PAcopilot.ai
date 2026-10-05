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
from src.services.monitoring_rules_service import run_due_monitors
from src.tm1.health.score import scan_due_connections
from src.tm1.metadata.history import refresh_due_connections

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


@router.get("/refresh-metadata", response_model=ApiResponse[dict])
async def refresh_metadata(request: Request):
    """Re-extract the dependency map of connections not refreshed in a day."""

    _require_cron_secret(request)

    return ApiResponse(success=True, data=await refresh_due_connections())


@router.get("/model-health", response_model=ApiResponse[dict])
async def model_health(request: Request):
    """Re-scan the health of connections not scanned in a day."""

    _require_cron_secret(request)

    return ApiResponse(success=True, data=await scan_due_connections())


@router.api_route("/monitors", methods=["GET", "POST"], response_model=ApiResponse[dict])
async def monitors(request: Request):
    """Check every monitoring rule that is due.

    Vercel Hobby runs its cron once a day, so this is also meant to be
    called every 15 minutes by an outside scheduler (any service that can
    send the CRON_SECRET bearer header). Calling it more often is harmless:
    a rule is checked only when its interval has passed."""

    _require_cron_secret(request)

    return ApiResponse(success=True, data=await run_due_monitors())

