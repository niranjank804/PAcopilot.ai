import uuid

import pytest

from src.core import rate_limit
from src.core.config import settings
from src.core.exceptions import RateLimitedException


@pytest.fixture(autouse=True)
def clean_windows(monkeypatch):
    # Memory windows unless a test installs a shared store.
    monkeypatch.setattr(settings, "UPSTASH_REDIS_REST_URL", None)
    monkeypatch.setattr(settings, "UPSTASH_REDIS_REST_TOKEN", None)
    monkeypatch.setattr(rate_limit, "_client", None)
    rate_limit.reset()
    yield
    rate_limit.reset()


async def _enforce(user_id, org_id, user_limit=3, organization_limit=10):
    await rate_limit.enforce(
        scope="test",
        user_id=user_id,
        organization_id=org_id,
        user_limit=user_limit,
        organization_limit=organization_limit,
    )


async def test_requests_under_the_limit_pass():
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        await _enforce(user, org)


async def test_exceeding_the_user_limit_raises_with_retry_after():
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        await _enforce(user, org)

    with pytest.raises(RateLimitedException) as exc_info:
        await _enforce(user, org)

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "RATE_LIMITED"
    assert 0 < exc_info.value.retry_after <= settings.RATE_LIMIT_WINDOW_SECONDS


async def test_one_user_does_not_consume_another_users_allowance():
    org = uuid.uuid4()
    noisy, quiet = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        await _enforce(noisy, org)

    with pytest.raises(RateLimitedException):
        await _enforce(noisy, org)

    # The org window is far from full, so the quiet user is unaffected.
    await _enforce(quiet, org)


async def test_organization_limit_caps_the_whole_org():
    org = uuid.uuid4()

    for _ in range(4):
        await _enforce(uuid.uuid4(), org, user_limit=100, organization_limit=4)

    with pytest.raises(RateLimitedException) as exc_info:
        await _enforce(uuid.uuid4(), org, user_limit=100, organization_limit=4)

    assert "organization" in str(exc_info.value).lower()


async def test_organizations_are_independent():
    org_a, org_b = uuid.uuid4(), uuid.uuid4()

    for _ in range(4):
        await _enforce(uuid.uuid4(), org_a, user_limit=100, organization_limit=4)

    await _enforce(uuid.uuid4(), org_b, user_limit=100, organization_limit=4)


async def test_window_slides(monkeypatch):
    user, org = uuid.uuid4(), uuid.uuid4()
    now = [1_000.0]

    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])

    for _ in range(3):
        await _enforce(user, org)

    with pytest.raises(RateLimitedException):
        await _enforce(user, org)

    # Past the window, the old hits age out and the budget is back.
    now[0] += settings.RATE_LIMIT_WINDOW_SECONDS + 1
    await _enforce(user, org)


async def test_disabling_the_limiter_is_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(50):
        await _enforce(user, org)


async def test_idle_keys_are_swept(monkeypatch):
    # Sweep on every hit so the assertions below are about staleness, not
    # about when the counter happens to fire.
    monkeypatch.setattr(rate_limit, "_SWEEP_EVERY", 1)

    now = [1_000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])

    for _ in range(4):
        await _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 8  # one user + one org key each

    # The sweep waits out the LONGEST configured window, so an auth window
    # (5 minutes) is never evicted while it is still enforcing.
    longest = max(
        settings.RATE_LIMIT_WINDOW_SECONDS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )

    now[0] += settings.RATE_LIMIT_WINDOW_SECONDS + 1
    await _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 10, "auth-length windows evicted early"

    now[0] += longest + 1
    await _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 2


# ----------------------------------------------------------------------
# Shared windows (Upstash Redis over REST)
# ----------------------------------------------------------------------


class FakeUpstash:
    """Answers the limiter's EVAL the way the Lua script does: a sorted
    set of hit times per key, pruned to the window."""

    def __init__(self, fail: bool = False):
        self.sets: dict[str, list[float]] = {}
        self.calls = 0
        self.fail = fail

    def handler(self, request):
        import httpx

        self.calls += 1
        assert request.headers["Authorization"] == "Bearer test-token"
        if self.fail:
            return httpx.Response(503, json={"error": "unavailable"})

        command, _script, _numkeys, key, now, window, limit, _member = (
            __import__("json").loads(request.content)
        )
        assert command == "EVAL"
        now, window, limit = float(now), float(window), int(limit)
        hits = [t for t in self.sets.get(key, []) if t > now - window]
        if len(hits) >= limit:
            self.sets[key] = hits
            return httpx.Response(200, json={"result": str(window - (now - min(hits)))})
        self.sets[key] = hits + [now]
        return httpx.Response(200, json={"result": ""})


@pytest.fixture
def upstash(monkeypatch):
    import httpx

    def install(fake: FakeUpstash):
        monkeypatch.setattr(settings, "UPSTASH_REDIS_REST_URL", "https://fake.upstash.io/")
        monkeypatch.setattr(settings, "UPSTASH_REDIS_REST_TOKEN", "test-token")
        monkeypatch.setattr(
            rate_limit, "_client", httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        )
        return fake

    return install


async def test_windows_are_shared_through_upstash(upstash):
    fake = upstash(FakeUpstash())
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        await _enforce(user, org)

    # Another instance's memory would be empty; the shared window is not.
    rate_limit._WINDOWS.clear()
    with pytest.raises(RateLimitedException) as exc_info:
        await _enforce(user, org)

    assert 0 < exc_info.value.retry_after <= settings.RATE_LIMIT_WINDOW_SECONDS
    assert f"ratelimit:test:user:{user}" in fake.sets
    assert not rate_limit._WINDOWS  # nothing kept in memory while Redis answers


async def test_an_unreachable_store_falls_back_to_per_instance_limits(upstash):
    fake = upstash(FakeUpstash(fail=True))
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        await _enforce(user, org)

    # Still limited — by this instance's own memory — rather than failing
    # the request or letting everything through.
    with pytest.raises(RateLimitedException):
        await _enforce(user, org)
    assert fake.calls >= 4


async def test_login_throttle_uses_the_shared_store(upstash):
    fake = upstash(FakeUpstash())

    for _ in range(2):
        await rate_limit.enforce_ip(scope="auth:login", client_ip="203.0.113.9", limit=2)
    with pytest.raises(RateLimitedException):
        await rate_limit.enforce_ip(scope="auth:login", client_ip="203.0.113.9", limit=2)

    assert "ratelimit:auth:login:ip:203.0.113.9" in fake.sets


def test_the_vercel_marketplace_variable_names_are_accepted(monkeypatch):
    from src.core.config import Settings

    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "token-from-vercel")

    loaded = Settings()
    assert loaded.UPSTASH_REDIS_REST_URL == "https://example.upstash.io"
    assert loaded.UPSTASH_REDIS_REST_TOKEN == "token-from-vercel"
