"""What a failed TM1 call tells the caller, and what it costs the process.

TM1py's exception text carries the response body and every header the
server sent. For a server whose address the caller chose, that made the
error message a way to read whatever answered. And every call ran on
asyncio's shared default executor, where a TM1 server that stopped
answering could hold every thread the process had.
"""

import asyncio
import threading
import uuid
from unittest.mock import AsyncMock

import pytest
from TM1py.Exceptions import TM1pyNetworkException, TM1pyRestException, TM1pyTimeout

import src.tm1.resilience as resilience
from src.core.config import settings
from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1ConnectionError,
    TM1NotFoundError,
)
from src.tm1.resilience import (
    TIMEOUT_GRACE_SECONDS,
    _breakers,
    call_with_resilience,
    describe_failure,
)

SECRET_HEADER = "X-Internal-Token: do-not-leak"
SECRET_BODY = "<html>internal admin console</html>"


def _rest_error(status_code, reason="Reason"):
    return TM1pyRestException(
        response=SECRET_BODY,
        status_code=status_code,
        reason=reason,
        headers={"X-Internal-Token": "do-not-leak"},
    )


@pytest.fixture(autouse=True)
def _fresh_breakers():
    _breakers.clear()
    yield
    _breakers.clear()


def test_rest_failures_are_described_without_body_or_headers():
    message = describe_failure(_rest_error(500, "Internal Server Error"))

    assert message == "TM1 returned HTTP 500 (Internal Server Error)."
    assert "do-not-leak" not in message
    assert "internal admin console" not in message


def test_timeouts_and_network_failures_are_described_generically():
    assert "did not respond" in describe_failure(asyncio.TimeoutError())
    assert "did not respond" in describe_failure(
        TM1pyTimeout(method="GET", url="https://x/y", timeout=1)
    )
    assert "could not be reached" in describe_failure(
        TM1pyNetworkException(
            response=SECRET_BODY, status_code=0, reason="Network", headers={}
        )
    )
    assert SECRET_BODY not in describe_failure(
        TM1pyNetworkException(
            response=SECRET_BODY, status_code=0, reason="Network", headers={}
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, expected",
    [(401, TM1AuthenticationError), (404, TM1NotFoundError), (400, TM1ConnectionError)],
)
async def test_typed_errors_carry_only_the_shape_of_the_failure(status_code, expected):
    def failing():
        raise _rest_error(status_code)

    with pytest.raises(expected) as excinfo:
        await call_with_resilience(uuid.uuid4(), failing)

    assert "do-not-leak" not in excinfo.value.message
    assert "internal admin console" not in excinfo.value.message
    assert f"HTTP {status_code}" in excinfo.value.message


@pytest.mark.asyncio
async def test_exhausted_retries_do_not_leak_the_last_response(monkeypatch):
    monkeypatch.setattr(resilience.asyncio, "sleep", AsyncMock(return_value=None))

    def failing():
        raise _rest_error(503, "Service Unavailable")

    with pytest.raises(TM1ConnectionError) as excinfo:
        await call_with_resilience(uuid.uuid4(), failing, max_retries=1)

    assert "after 2 attempts" in excinfo.value.message
    assert "HTTP 503" in excinfo.value.message
    assert "do-not-leak" not in excinfo.value.message


@pytest.mark.asyncio
async def test_calls_run_on_the_dedicated_bounded_pool():
    seen: list[str] = []

    def record():
        seen.append(threading.current_thread().name)
        return "ok"

    assert await call_with_resilience(uuid.uuid4(), record) == "ok"

    assert seen and seen[0].startswith("tm1")
    assert resilience._tm1_executor()._max_workers == settings.TM1_MAX_CONCURRENT_CALLS


@pytest.mark.asyncio
async def test_the_outer_wait_gives_tm1pys_own_timeout_a_head_start(monkeypatch):
    """The thread's own timeout is what ends the request; the asyncio wait
    is the backstop, so it must not fire first."""

    captured: dict = {}

    async def fake_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(resilience.asyncio, "wait_for", fake_wait_for)

    await call_with_resilience(uuid.uuid4(), lambda: "ok", timeout=7.0)

    assert captured["timeout"] == 7.0 + TIMEOUT_GRACE_SECONDS
