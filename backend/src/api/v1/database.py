"""Database connectivity probe.

This endpoint previously returned, without authentication:

  * the full PostgreSQL version string — an exact patch level maps
    directly onto published CVEs;
  * the database name;
  * on failure, str(exception) — and an asyncpg/SQLAlchemy connection
    error carries the host, port and username from the connection string.

An unauthenticated caller could therefore learn where the database lives
and who connects to it. It now reports connectivity as a bare status to
anyone, and diagnostic detail only to an administrator.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from src.api.dependencies.permissions import require_permission
from src.database.session import AsyncSessionLocal
from src.schemas.auth import UserResponse

router = APIRouter()


async def _probe() -> tuple[bool, str | None]:
    """(reachable, exception type name)."""

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

        return True, None
    except Exception as exc:
        return False, type(exc).__name__


@router.get("/database", tags=["Database"])
async def database_health():
    """Connectivity only. Safe to expose; reveals nothing about the server."""

    reachable, _ = await _probe()

    return {"status": "connected" if reachable else "unavailable"}


@router.get("/database/details", tags=["Database"])
async def database_details(
    # organization.read is the closest existing administrative permission:
    # Super Admin and Organization Admin hold it, ordinary roles do not.
    current_user: UserResponse = Depends(require_permission("organization.read")),
):
    """Diagnostics for an administrator.

    Still no connection string, credentials or raw driver message — the
    exception *type* distinguishes a timeout from an auth failure without
    naming the host or user.
    """

    reachable, error_type = await _probe()

    if not reachable:
        return {"status": "unavailable", "error": error_type}

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT version()"))
        version = result.scalar()

    return {"status": "connected", "postgresql": version}
