"""Per-user and per-organization request rate limiting.

Before this, an authenticated caller could issue unbounded requests. That
matters most on the AI endpoints: each one costs real provider money and
occupies a database connection for the length of an agent turn, so a
single scripted loop was both an uncapped bill and a denial of service
against everyone else's pool slots.

Two windows are enforced on every guarded request — one for the user, one
for their organization — so one runaway client cannot consume the whole
organization's budget, and one organization cannot starve the others.

**Shared when Upstash is configured.** On Vercel every warm instance is a
separate process, so windows kept in memory multiply the limit by the
instance count — and the login throttle, the one standing between
/auth/login and credential stuffing, stops limiting without an error.
With UPSTASH_REDIS_REST_URL and _TOKEN set (the Vercel Marketplace
integration sets them, as KV_REST_API_URL and _TOKEN), every window lives
in Redis and all instances share it.

Without them, or if Redis cannot be reached, the windows fall back to
this process's memory: the previous behaviour, limits per instance. A
Redis outage therefore loosens limits rather than failing every request —
the failure mode chosen on purpose, since refusing all logins because the
limiter's store is down would be an outage of its own.
"""

import logging
import time
import uuid
from collections import defaultdict, deque

import httpx

from src.core.config import settings
from src.core.exceptions import RateLimitedException

logger = logging.getLogger(__name__)

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


def _check_memory(
    key: str,
    limit: int,
    now: float,
    window: float,
) -> float | None:
    hits = _WINDOWS[key]

    while hits and now - hits[0] >= window:
        hits.popleft()

    if len(hits) >= limit:
        # The oldest hit is what has to age out before there is room again.
        return max(0.0, window - (now - hits[0]))

    hits.append(now)

    return None


# The same sliding-window log, in a Redis sorted set, in one atomic step:
# drop hits older than the window, count, and either refuse (with the time
# until the oldest ages out) or record this hit. Atomic so two instances
# cannot both see room for the last slot.
_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return tostring(window - (now - tonumber(oldest[2])))
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return ''
"""

_SHARED_TIMEOUT = 1.5
# One warning per this many seconds while Redis is failing, not one per
# request.
_WARN_EVERY = 60.0
_last_warning = 0.0
_client: httpx.AsyncClient | None = None


def _shared_store() -> tuple[str, str] | None:
    url, token = settings.UPSTASH_REDIS_REST_URL, settings.UPSTASH_REDIS_REST_TOKEN
    return (url.rstrip("/"), token) if url and token else None


async def _check_shared(
    store: tuple[str, str],
    key: str,
    limit: int,
    window: float,
) -> float | None:
    global _client

    if _client is None:
        _client = httpx.AsyncClient(timeout=_SHARED_TIMEOUT)

    url, token = store
    now = time.time()  # wall clock: shared across instances
    response = await _client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=[
            "EVAL", _SLIDING_WINDOW, "1", f"ratelimit:{key}",
            repr(now), repr(float(window)), str(limit), f"{now}:{uuid.uuid4().hex}",
        ],
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(body["error"])

    result = body.get("result") or ""
    return max(0.0, float(result)) if result else None


async def _check(
    key: str,
    limit: int,
    window: float | None = None,
) -> float | None:
    """Record a hit. Returns seconds until retry if the limit is exceeded."""

    global _last_warning

    window = (
        window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS
    )

    store = _shared_store()
    if store:
        try:
            return await _check_shared(store, key, limit, window)
        except Exception as exc:
            now = time.monotonic()
            if now - _last_warning > _WARN_EVERY:
                _last_warning = now
                # The type only: an HTTP error can echo the request URL.
                logger.warning(
                    "Shared rate-limit store unavailable (%s); limiting per "
                    "instance until it answers again.",
                    type(exc).__name__,
                )

    return _check_memory(key, limit, time.monotonic(), window)


async def enforce(
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
    retry_after = await _check(f"{scope}:org:{organization_id}", organization_limit)

    if retry_after is not None:
        raise RateLimitedException(
            "Your organization has made too many requests. Try again in "
            f"{int(retry_after) + 1}s.",
            retry_after=retry_after,
        )

    retry_after = await _check(f"{scope}:user:{user_id}", user_limit)

    if retry_after is not None:
        raise RateLimitedException(
            f"Too many requests. Try again in {int(retry_after) + 1}s.",
            retry_after=retry_after,
        )


async def enforce_ip(
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

    effective_window = (
        window
        if window is not None
        else settings.AUTH_RATE_LIMIT_WINDOW_SECONDS
    )

    retry_after = await _check(
        f"{scope}:ip:{client_ip}", limit, window=effective_window
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


def client_ip_of(request) -> str | None:
    """The real client address, honouring a trusted proxy chain.

    Every IP-keyed limit was reading `request.client.host` directly.
    Behind a reverse proxy that is the *proxy's* address, so all clients
    share one bucket: the login and password-reset throttles stop being
    per-attacker and become a global cap that a single busy proxy can
    exhaust for everyone. `settings.TRUSTED_PROXY_COUNT` existed for this
    and was never wired up.

    X-Forwarded-For is appended to by each hop, so the rightmost entries
    are the ones added by infrastructure we control. Taking the entry
    `TRUSTED_PROXY_COUNT` from the right gives the address our own edge
    observed. Reading the *leftmost* entry instead — the common mistake —
    trusts a value the client supplied, letting anyone forge a new
    identity per request and bypass the limit entirely.
    """

    trusted = max(0, settings.TRUSTED_PROXY_COUNT)

    if trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [part.strip() for part in forwarded.split(",") if part.strip()]

        if hops:
            # Clamp: fewer hops than configured means the request did not
            # traverse the whole expected chain, so use the leftmost we
            # actually have rather than indexing off the end.
            index = min(trusted, len(hops))

            return hops[len(hops) - index]

    return request.client.host if request.client else None
