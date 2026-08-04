"""Per-user and per-organization request rate limiting.

Before this, an authenticated caller could issue unbounded requests. That
matters most on the AI endpoints: each one costs real provider money and
occupies a database connection for the length of an agent turn, so a
single scripted loop was both an uncapped bill and a denial of service
against everyone else's pool slots.

Two windows are enforced on every guarded request — one for the user, one
for their organization — so one runaway client cannot consume the whole
organization's budget, and one organization cannot starve the others.

**Single-process only.** State lives in this process's memory, so the
effective limit is multiplied by the number of worker processes. The
current deployment runs `gunicorn --workers 2` (render.yaml), so real
limits today are **twice** the configured values, and adding instances
multiplies them further. That is a deliberate first step, not a finished
design: it removes the unbounded case without adding Redis to the
deployment. Move `_WINDOWS` to a shared store before scaling out.
"""

import time
from collections import defaultdict, deque

from src.core.config import settings
from src.core.exceptions import RateLimitedException

# key -> timestamps of the hits still inside the window
_WINDOWS: dict[str, deque[float]] = defaultdict(deque)

# Keys are unbounded in principle (one per user, per org, per scope), so
# sweep idle ones out rather than growing forever in a long-lived process.
_SWEEP_EVERY = 1_000
_hits_since_sweep = 0


def _sweep(now: float) -> None:
    stale = [
        key
        for key, hits in _WINDOWS.items()
        if not hits
        or now - hits[-1]
        > max(
            settings.RATE_LIMIT_WINDOW_SECONDS,
            settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
        )
    ]

    for key in stale:
        del _WINDOWS[key]


def _check(
    key: str,
    limit: int,
    now: float,
    window: float | None = None,
) -> float | None:
    """Record a hit. Returns seconds until retry if the limit is exceeded."""

    window = (
        window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS
    )
    hits = _WINDOWS[key]

    while hits and now - hits[0] >= window:
        hits.popleft()

    if len(hits) >= limit:
        # The oldest hit is what has to age out before there is room again.
        return max(0.0, window - (now - hits[0]))

    hits.append(now)

    return None


def enforce(
    *,
    scope: str,
    user_id,
    organization_id,
    user_limit: int,
    organization_limit: int,
) -> None:
    """Raise RateLimitedException if either window is full."""

    global _hits_since_sweep

    if not settings.RATE_LIMIT_ENABLED:
        return

    now = time.monotonic()

    _hits_since_sweep += 1

    if _hits_since_sweep >= _SWEEP_EVERY:
        _hits_since_sweep = 0
        _sweep(now)

    # Organization first: if the org is over budget, the user's own
    # allowance should not be spent on a request that cannot proceed.
    retry_after = _check(
        f"{scope}:org:{organization_id}", organization_limit, now
    )

    if retry_after is not None:
        raise RateLimitedException(
            "Your organization has made too many requests. Try again in "
            f"{int(retry_after) + 1}s.",
            retry_after=retry_after,
        )

    retry_after = _check(f"{scope}:user:{user_id}", user_limit, now)

    if retry_after is not None:
        raise RateLimitedException(
            f"Too many requests. Try again in {int(retry_after) + 1}s.",
            retry_after=retry_after,
        )


def enforce_ip(
    *,
    scope: str,
    client_ip: str | None,
    limit: int,
    window: float | None = None,
) -> None:
    """Throttle an unauthenticated endpoint by source address.

    Login, registration and password reset are reachable without a token,
    so there is no user or organization to key on — the client address is
    all there is. That makes this weaker than the authenticated limiter
    (a botnet or a rotating proxy pool spreads across many addresses), but
    it stops the single-host credential-stuffing and reset-spam cases that
    are otherwise unbounded.

    A request with no resolvable address is not throttled rather than
    being lumped into one shared bucket, which would let one such caller
    lock out every other.
    """

    if not settings.RATE_LIMIT_ENABLED or not client_ip:
        return

    now = time.monotonic()
    effective_window = (
        window
        if window is not None
        else settings.AUTH_RATE_LIMIT_WINDOW_SECONDS
    )

    retry_after = _check(
        f"{scope}:ip:{client_ip}", limit, now, window=effective_window
    )

    if retry_after is not None:
        raise RateLimitedException(
            "Too many attempts from this address. Try again in "
            f"{int(retry_after) + 1}s.",
            retry_after=retry_after,
        )


def reset() -> None:
    """Clear all windows. For tests — never call this from request code."""

    global _hits_since_sweep

    _WINDOWS.clear()
    _hits_since_sweep = 0
