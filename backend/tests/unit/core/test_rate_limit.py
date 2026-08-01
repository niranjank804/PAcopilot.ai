import uuid

import pytest

from src.core import rate_limit
from src.core.config import settings
from src.core.exceptions import RateLimitedException


@pytest.fixture(autouse=True)
def clean_windows():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _enforce(user_id, org_id, user_limit=3, organization_limit=10):
    rate_limit.enforce(
        scope="test",
        user_id=user_id,
        organization_id=org_id,
        user_limit=user_limit,
        organization_limit=organization_limit,
    )


def test_requests_under_the_limit_pass():
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        _enforce(user, org)


def test_exceeding_the_user_limit_raises_with_retry_after():
    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        _enforce(user, org)

    with pytest.raises(RateLimitedException) as exc_info:
        _enforce(user, org)

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "RATE_LIMITED"
    assert 0 < exc_info.value.retry_after <= settings.RATE_LIMIT_WINDOW_SECONDS


def test_one_user_does_not_consume_another_users_allowance():
    org = uuid.uuid4()
    noisy, quiet = uuid.uuid4(), uuid.uuid4()

    for _ in range(3):
        _enforce(noisy, org)

    with pytest.raises(RateLimitedException):
        _enforce(noisy, org)

    # The org window is far from full, so the quiet user is unaffected.
    _enforce(quiet, org)


def test_organization_limit_caps_the_whole_org():
    org = uuid.uuid4()

    for _ in range(4):
        _enforce(uuid.uuid4(), org, user_limit=100, organization_limit=4)

    with pytest.raises(RateLimitedException) as exc_info:
        _enforce(uuid.uuid4(), org, user_limit=100, organization_limit=4)

    assert "organization" in str(exc_info.value).lower()


def test_organizations_are_independent():
    org_a, org_b = uuid.uuid4(), uuid.uuid4()

    for _ in range(4):
        _enforce(uuid.uuid4(), org_a, user_limit=100, organization_limit=4)

    _enforce(uuid.uuid4(), org_b, user_limit=100, organization_limit=4)


def test_window_slides(monkeypatch):
    user, org = uuid.uuid4(), uuid.uuid4()
    now = [1_000.0]

    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])

    for _ in range(3):
        _enforce(user, org)

    with pytest.raises(RateLimitedException):
        _enforce(user, org)

    # Past the window, the old hits age out and the budget is back.
    now[0] += settings.RATE_LIMIT_WINDOW_SECONDS + 1
    _enforce(user, org)


def test_disabling_the_limiter_is_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    user, org = uuid.uuid4(), uuid.uuid4()

    for _ in range(50):
        _enforce(user, org)


def test_idle_keys_are_swept(monkeypatch):
    # Sweep on every hit so the assertions below are about staleness, not
    # about when the counter happens to fire.
    monkeypatch.setattr(rate_limit, "_SWEEP_EVERY", 1)

    now = [1_000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])

    for _ in range(4):
        _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 8  # one user + one org key each

    # The sweep waits out the LONGEST configured window, so an auth window
    # (5 minutes) is never evicted while it is still enforcing.
    longest = max(
        settings.RATE_LIMIT_WINDOW_SECONDS,
        settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )

    now[0] += settings.RATE_LIMIT_WINDOW_SECONDS + 1
    _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 10, "auth-length windows evicted early"

    now[0] += longest + 1
    _enforce(uuid.uuid4(), uuid.uuid4(), organization_limit=100)

    assert len(rate_limit._WINDOWS) == 2
