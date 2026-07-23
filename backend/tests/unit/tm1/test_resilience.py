import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from TM1py.Exceptions import TM1pyNetworkException, TM1pyRestException

from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1ConnectionError,
    TM1NotFoundError,
)
from src.tm1.resilience import (
    CircuitBreaker,
    CircuitState,
    _breakers,
    call_with_resilience,
    get_circuit_breaker,
    peek_circuit_breaker,
    remove_circuit_breaker,
)


def _network_error():
    return TM1pyNetworkException(
        response="unreachable", status_code=0, reason="Network Error", headers={}
    )


def _rest_error(status_code):
    return TM1pyRestException(
        response="error", status_code=status_code, reason="Error", headers={}
    )


# --- CircuitBreaker state machine -------------------------------------------


def test_circuit_breaker_opens_after_threshold_failures():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_circuit_breaker_rejects_calls_while_open():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30)
    breaker.record_failure()

    with pytest.raises(TM1ConnectionError):
        breaker.before_call()


def test_circuit_breaker_half_opens_after_cooldown():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0)
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    breaker.before_call()  # cooldown already elapsed (0s)
    assert breaker.state == CircuitState.HALF_OPEN


def test_circuit_breaker_closes_on_half_open_success():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0)
    breaker.record_failure()
    breaker.before_call()
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


def test_circuit_breaker_reopens_on_half_open_failure():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0)
    breaker.record_failure()
    breaker.before_call()
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_get_circuit_breaker_returns_same_instance_for_same_connection():
    connection_id = uuid.uuid4()

    first = get_circuit_breaker(connection_id)
    second = get_circuit_breaker(connection_id)

    assert first is second

    remove_circuit_breaker(connection_id)


def test_remove_circuit_breaker_resets_state():
    connection_id = uuid.uuid4()
    breaker = get_circuit_breaker(connection_id)
    breaker.record_failure()

    remove_circuit_breaker(connection_id)

    fresh = get_circuit_breaker(connection_id)
    assert fresh.state == CircuitState.CLOSED
    assert fresh is not breaker

    remove_circuit_breaker(connection_id)


def test_peek_circuit_breaker_returns_none_for_untouched_connection():
    connection_id = uuid.uuid4()

    assert peek_circuit_breaker(connection_id) is None
    assert connection_id not in _breakers


def test_peek_circuit_breaker_reflects_real_state():
    connection_id = uuid.uuid4()
    breaker = get_circuit_breaker(connection_id)
    breaker.record_failure()

    peeked = peek_circuit_breaker(connection_id)

    assert peeked is breaker
    assert peeked.failure_count == 1

    remove_circuit_breaker(connection_id)


def test_peek_circuit_breaker_does_not_create_an_entry():
    connection_id = uuid.uuid4()

    peek_circuit_breaker(connection_id)
    peek_circuit_breaker(connection_id)

    assert connection_id not in _breakers


# --- call_with_resilience: retry behavior -----------------------------------


@pytest.mark.asyncio
async def test_call_with_resilience_returns_result_on_success():
    connection_id = uuid.uuid4()
    func = MagicMock(return_value="ok")

    result = await call_with_resilience(connection_id, func, max_retries=0)

    assert result == "ok"
    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_retries_transient_failure_then_succeeds(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.tm1.resilience.asyncio.sleep", AsyncMock(return_value=None)
    )

    connection_id = uuid.uuid4()
    func = MagicMock(side_effect=[_network_error(), _network_error(), "ok"])

    result = await call_with_resilience(
        connection_id, func, max_retries=3, base_delay=0.01
    )

    assert result == "ok"
    assert func.call_count == 3

    breaker = get_circuit_breaker(connection_id)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_exhausts_retries_and_raises(monkeypatch):
    monkeypatch.setattr(
        "src.tm1.resilience.asyncio.sleep", AsyncMock(return_value=None)
    )

    connection_id = uuid.uuid4()
    func = MagicMock(side_effect=_network_error())

    with pytest.raises(TM1ConnectionError):
        await call_with_resilience(
            connection_id, func, max_retries=2, base_delay=0.01
        )

    assert func.call_count == 3  # initial attempt + 2 retries

    # One call_with_resilience invocation (however many internal retries it
    # took) counts as a single breaker failure, not one per raw attempt.
    breaker = get_circuit_breaker(connection_id)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 1

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_repeated_exhausted_calls_open_the_circuit(monkeypatch):
    monkeypatch.setattr(
        "src.tm1.resilience.asyncio.sleep", AsyncMock(return_value=None)
    )

    connection_id = uuid.uuid4()
    breaker = get_circuit_breaker(connection_id)
    breaker.failure_threshold = 2
    func = MagicMock(side_effect=_network_error())

    for _ in range(2):
        with pytest.raises(TM1ConnectionError):
            await call_with_resilience(
                connection_id, func, max_retries=0, base_delay=0.01
            )

    assert breaker.state == CircuitState.OPEN

    # A third call is rejected immediately, without invoking func again.
    call_count_before = func.call_count
    with pytest.raises(TM1ConnectionError):
        await call_with_resilience(connection_id, func, max_retries=0)
    assert func.call_count == call_count_before

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_does_not_retry_auth_error():
    connection_id = uuid.uuid4()
    func = MagicMock(side_effect=_rest_error(401))

    with pytest.raises(TM1AuthenticationError):
        await call_with_resilience(connection_id, func, max_retries=3)

    assert func.call_count == 1

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_does_not_retry_not_found():
    connection_id = uuid.uuid4()
    func = MagicMock(side_effect=_rest_error(404))

    with pytest.raises(TM1NotFoundError):
        await call_with_resilience(connection_id, func, max_retries=3)

    assert func.call_count == 1

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_retries_server_error():
    connection_id = uuid.uuid4()
    func = MagicMock(side_effect=[_rest_error(503), "ok"])

    result = await call_with_resilience(
        connection_id, func, max_retries=1, base_delay=0.01
    )

    assert result == "ok"
    assert func.call_count == 2

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_times_out(monkeypatch):
    monkeypatch.setattr(
        "src.tm1.resilience.asyncio.sleep", AsyncMock(return_value=None)
    )

    def slow_call():
        import time as time_module

        time_module.sleep(0.2)
        return "too slow"

    connection_id = uuid.uuid4()

    with pytest.raises(TM1ConnectionError):
        await call_with_resilience(
            connection_id,
            slow_call,
            timeout=0.01,
            max_retries=0,
        )

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_rejects_immediately_when_circuit_open():
    connection_id = uuid.uuid4()
    breaker = get_circuit_breaker(connection_id)
    breaker.state = CircuitState.OPEN
    breaker.opened_at = None

    func = MagicMock()

    # opened_at is None with state OPEN -> before_call treats it as still open
    # (no elapsed-cooldown reference point), so it must reject without calling func.
    with pytest.raises(TM1ConnectionError):
        await call_with_resilience(connection_id, func, max_retries=3)

    func.assert_not_called()

    remove_circuit_breaker(connection_id)


@pytest.mark.asyncio
async def test_call_with_resilience_translates_raw_requests_connection_error():
    """TM1py lets raw requests.exceptions.ConnectionError escape for DNS and
    socket-level failures (e.g. during TM1Service construction) instead of
    wrapping them in TM1pyNetworkException. Found via live browser testing:
    an unreachable host produced a 500 instead of a clean TM1ConnectionError."""

    import requests

    connection_id = uuid.uuid4()
    func = MagicMock(
        side_effect=requests.exceptions.ConnectionError("name resolution failed")
    )

    with pytest.raises(TM1ConnectionError):
        await call_with_resilience(
            connection_id, func, max_retries=1, base_delay=0.01
        )

    # Retried (transient), then translated — never leaked the raw exception.
    assert func.call_count == 2

    remove_circuit_breaker(connection_id)
