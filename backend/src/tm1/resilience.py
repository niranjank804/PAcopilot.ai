import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Callable

import requests
from TM1py.Exceptions import (
    TM1pyNetworkException,
    TM1pyRestException,
    TM1pyTimeout,
)

from src.core.config import settings
from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1ConnectionError,
    TM1NotFoundError,
)

TRANSIENT_STATUS_THRESHOLD = 500


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:

    def __init__(self, failure_threshold: int, cooldown_seconds: float):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at: float | None = None

    def before_call(self) -> None:
        if self.state != CircuitState.OPEN:
            return

        if (
            self.opened_at is not None
            and (time.monotonic() - self.opened_at) >= self.cooldown_seconds
        ):
            self.state = CircuitState.HALF_OPEN
            return

        raise TM1ConnectionError(
            "Circuit breaker open: TM1 connection is currently unavailable."
        )

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1

        if self.state == CircuitState.HALF_OPEN or (
            self.failure_count >= self.failure_threshold
        ):
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


_breakers: dict[uuid.UUID, CircuitBreaker] = {}


def get_circuit_breaker(connection_id: uuid.UUID) -> CircuitBreaker:
    if connection_id not in _breakers:
        _breakers[connection_id] = CircuitBreaker(
            failure_threshold=settings.TM1_CIRCUIT_BREAKER_THRESHOLD,
            cooldown_seconds=settings.TM1_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        )

    return _breakers[connection_id]


def remove_circuit_breaker(connection_id: uuid.UUID) -> None:
    _breakers.pop(connection_id, None)


def peek_circuit_breaker(connection_id: uuid.UUID) -> CircuitBreaker | None:
    """Read-only lookup for monitoring — unlike get_circuit_breaker(), this
    never creates an entry, so merely observing a connection's status can't
    itself mutate breaker state."""

    return _breakers.get(connection_id)


async def call_with_resilience(
    connection_id: uuid.UUID,
    func: Callable,
    *args,
    timeout: float | None = None,
    max_retries: int | None = None,
    base_delay: float = 1.0,
    **kwargs,
) -> Any:
    breaker = get_circuit_breaker(connection_id)
    breaker.before_call()

    resolved_timeout = (
        timeout if timeout is not None else settings.TM1_REQUEST_TIMEOUT_SECONDS
    )
    resolved_max_retries = (
        max_retries if max_retries is not None else settings.TM1_MAX_RETRIES
    )

    delay = base_delay
    last_exc: Exception | None = None

    for attempt in range(resolved_max_retries + 1):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(func, *args, **kwargs),
                timeout=resolved_timeout,
            )
        except (
            TM1pyNetworkException,
            TM1pyTimeout,
            asyncio.TimeoutError,
            # TM1py lets raw requests exceptions escape for DNS/socket-level
            # failures (e.g. at TM1Service construction) instead of wrapping
            # them in TM1pyNetworkException — found via live browser testing.
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            last_exc = exc
        except TM1pyRestException as exc:
            if exc.status_code in (401, 403):
                raise TM1AuthenticationError(str(exc)) from exc

            if exc.status_code == 404:
                raise TM1NotFoundError(str(exc)) from exc

            if exc.status_code < TRANSIENT_STATUS_THRESHOLD:
                raise TM1ConnectionError(str(exc)) from exc

            last_exc = exc
        else:
            breaker.record_success()

            return result

        if attempt < resolved_max_retries:
            await asyncio.sleep(delay)
            delay *= 2

    breaker.record_failure()

    raise TM1ConnectionError(
        f"TM1 request failed after {resolved_max_retries + 1} attempts: {last_exc}"
    ) from last_exc
