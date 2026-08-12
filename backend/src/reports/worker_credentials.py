"""Minting and checking the two secrets a worker holds.

Why not one permanent API key: a static key that both identifies a
machine and authorizes every call is a single value that, once leaked
(a log line, a config file in a backup, a screenshot in a ticket), grants
an attacker the customer's whole report queue until somebody notices.
The split here means:

* the enrollment token is single-use, expiring, and can only be spent to
  complete enrollment — stealing it after enrollment gets nothing;
* the credential never travels except to the token endpoint;
* everything else uses a JWT that expires in minutes, so a captured
  request header stops being useful almost immediately;
* rotation is a version bump, which invalidates issued tokens without
  needing a revocation table.

Storage is HMAC-SHA256 keyed with SECRET_KEY rather than argon2. These
are 256-bit machine-generated secrets, so there is no dictionary to
defend against and a password KDF's work factor would only slow down the
legitimate token endpoint. Keying the digest means a stolen database
snapshot alone cannot be used to verify guesses offline.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from src.core.config import settings
from src.core.exceptions import AuthenticationException

# Distinguishes worker tokens from user access/refresh tokens signed with
# the same key. Without it a worker token would be accepted by
# get_current_user's decode path (and vice versa) purely because the
# signature checks out.
WORKER_TOKEN_TYPE = "worker_access"

# Prefixes make a leaked value identifiable at a glance — in a log, a
# support ticket, or a secret scanner — instead of looking like any other
# opaque blob.
_ENROLLMENT_PREFIX = "pacw-enroll-"
_SECRET_PREFIX = "pacw-secret-"


def generate_enrollment_token() -> str:
    return _ENROLLMENT_PREFIX + secrets.token_urlsafe(32)


def generate_worker_secret() -> str:
    return _SECRET_PREFIX + secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_secret(value: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False

    # compare_digest, not ==: string equality short-circuits on the first
    # differing byte and leaks the length of the shared prefix by timing.
    return hmac.compare_digest(hash_secret(value), expected_hash)


def enrollment_expiry(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)

    return moment + timedelta(
        minutes=settings.REPORT_WORKER_ENROLLMENT_TTL_MINUTES
    )


def create_worker_token(
    *,
    worker_id: uuid.UUID,
    organization_id: uuid.UUID,
    secret_version: int,
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds).

    `org` and `sv` are in the token so the hot path — every heartbeat,
    claim and progress update — can reject an obviously wrong caller
    before touching the database, while still re-reading the worker row
    to confirm it has not been disabled since the token was issued.
    """

    issued_at = datetime.now(UTC)
    expires_in = settings.REPORT_WORKER_TOKEN_EXPIRE_MINUTES * 60
    expires_at = issued_at + timedelta(seconds=expires_in)

    payload = {
        "sub": str(worker_id),
        "type": WORKER_TOKEN_TYPE,
        "org": str(organization_id),
        "sv": secret_version,
        "iat": issued_at,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }

    token = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return token, expires_in


def decode_worker_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise AuthenticationException("Invalid or expired worker token.")

    if payload.get("type") != WORKER_TOKEN_TYPE:
        raise AuthenticationException("Invalid or expired worker token.")

    return payload
