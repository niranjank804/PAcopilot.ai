"""Authenticating a worker process, as distinct from a human.

This is not a second authentication system — it reuses the same signing
key, the same `jose` primitives, and the same `AuthenticationException`
handling as user auth. What differs is the subject: a worker is a
machine bound to exactly one organization, with no user, no roles, and
no permissions beyond "run my own organization's report jobs".

Keeping the two token families apart matters. A worker token and a user
token signed with the same key are cryptographically indistinguishable
unless something separates them, so `type` is checked on both sides:
`decode_worker_token()` rejects a user token here, and
`get_current_user()` rejects a worker token there (it requires
`type == "access"`). Without that, a stolen worker credential would be
usable against the whole user-facing API.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_worker import ReportWorker
from src.database.session import get_db
from src.reports.worker_credentials import decode_worker_token
from src.reports.worker_service import worker_service

worker_security = HTTPBearer()


async def get_current_worker(
    credentials: HTTPAuthorizationCredentials = Depends(worker_security),
    db: AsyncSession = Depends(get_db),
) -> ReportWorker:
    """Resolve a bearer token to a live, still-authorized worker row.

    The token is re-validated against the database on every request
    rather than trusted for its lifetime, because everything that would
    revoke it — disabling the worker, rotating its credential, deleting
    it — happens after the token was minted.
    """

    payload = decode_worker_token(credentials.credentials)

    worker = await worker_service.resolve_token_subject(db, payload)

    # Same stamping get_current_user() performs, for the same reason: the
    # session-level tenancy filter reads organization_id from
    # session.info. A worker request that skipped this would run entirely
    # unfiltered if TENANCY_ENFORCEMENT_ENABLED is ever turned on.
    #
    # Cleared first because this session may have served a different
    # subject already (the test harness reuses one session per request).
    db.info.pop("organization_id", None)
    db.info["organization_id"] = worker.organization_id

    return worker
