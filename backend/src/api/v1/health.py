"""Liveness and readiness probes.

The previous implementation returned {"status": "healthy"} unconditionally,
so the platform reported green while its database was unreachable and a
broken deploy still received traffic.

Two endpoints, because they answer different questions:

* `/health` — is this process alive? Cheap, no dependencies. Decides
  whether to restart the container.
* `/health/ready` — can this process serve requests? Checks the database
  and reports pool saturation. Decides whether to route traffic.

Neither requires authentication, so neither returns anything an
unauthenticated caller shouldn't see: no versions, hostnames or
connection strings — only whether dependencies answer, and pool counters.
"""

import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from src.database.session import engine

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health():
    """Liveness — the process is up and serving."""

    return {"status": "healthy"}


@router.get("/health/ready", tags=["Health"])
async def readiness(response: Response):
    """Readiness — dependencies answer and the pool has headroom."""

    checks: dict[str, dict] = {}
    ready = True

    start = time.monotonic()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as exc:
        ready = False
        # Type only, never the message: a driver error can carry the host
        # and user from the connection string.
        checks["database"] = {"status": "error", "error": type(exc).__name__}

    pool = engine.pool
    capacity = pool.size() + pool._max_overflow
    in_use = pool.checkedout()

    # Reported, but deliberately NOT a readiness failure. Saturation is
    # transient backpressure; failing the probe would have the load
    # balancer pull this instance out and push its traffic onto the others,
    # saturating them in turn. Only a dependency that cannot answer at all
    # makes this instance unfit to serve.
    checks["db_pool"] = {
        "status": "ok" if in_use < capacity else "saturated",
        "in_use": in_use,
        "capacity": capacity,
    }

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if ready else "not_ready", "checks": checks}
