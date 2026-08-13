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

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import rate_limit
from src.core.config import settings
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

    # Bound what one credential can do. A worker is a machine on a
    # polling loop, so its legitimate rate is far above a human's — but
    # "far above" is not "unbounded", and until now every /worker/*
    # route was uncapped. A stolen credential could poll `claim` in a
    # tight loop against the database.
    #
    # Keyed on the worker rather than a user: the worker *is* the
    # principal here, and one runaway machine must not consume its
    # organization's whole budget.
    rate_limit.enforce(
        scope="worker",
        user_id=worker.id,
        organization_id=worker.organization_id,
        user_limit=settings.RATE_LIMIT_WORKER_PER_WINDOW,
        organization_limit=settings.RATE_LIMIT_WORKER_ORG_PER_WINDOW,
    )

    return worker


def worker_credential_throttle(request: Request) -> None:
    """IP throttle for the unauthenticated credential endpoints.

    `/worker/token` and `/worker/enroll` accept a secret and answer
    whether it was right — the same shape of risk as `/auth/login`, and
    the last unbounded endpoints in the application. There is no
    authenticated identity to key on yet, so the client address is all
    there is.

    Weaker than the authenticated limiter (a rotating proxy pool spreads
    across addresses), but it closes the single-host guessing case,
    which is the one that is otherwise free.
    """

    rate_limit.enforce_ip(
        scope="worker_credential",
        client_ip=rate_limit.client_ip_of(request),
        limit=settings.RATE_LIMIT_WORKER_CREDENTIAL_IP_PER_WINDOW,
        window=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
