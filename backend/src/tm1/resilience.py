import asyncio
import contextvars
import functools
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Callable

import requests
from TM1py.Exceptions import (
    TM1pyNetworkException,
    TM1pyRestException,
    TM1pyTimeout,
)

from src.core.config import settings
from src.core.logging import app_logger
from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1ConnectionError,
    TM1NotFoundError,
)

TRANSIENT_STATUS_THRESHOLD = 500

# How much longer than TM1py's own timeout the caller waits before giving
# up on the thread. TM1py's timeout (set in build_tm1_kwargs) is what
# actually ends the request and frees the thread; this outer wait is the
# backstop for the stretches it does not cover — DNS resolution and the
# TLS handshake happen before the socket timeout starts.
TIMEOUT_GRACE_SECONDS = 5.0

_executor: ThreadPoolExecutor | None = None


def _tm1_executor() -> ThreadPoolExecutor:
    """The pool every TM1 call runs on.

    Dedicated rather than asyncio's default executor: a TM1 server that
    stops answering holds a thread per call until the timeout, and with
    the shared pool that starved smtplib, boto3 and everything else that
    uses to_thread. Now it can hold at most TM1_MAX_CONCURRENT_CALLS, and
    only its own.
    """

    global _executor

    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.TM1_MAX_CONCURRENT_CALLS,
            thread_name_prefix="tm1",
        )

    return _executor


async def _run_in_tm1_thread(func: Callable, *args, **kwargs) -> Any:
    # Same shape as asyncio.to_thread: the context is copied so the
    # request id reaches the log lines the call writes.
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()

    return await loop.run_in_executor(
        _tm1_executor(),
        functools.partial(context.run, func, *args, **kwargs),
    )


def describe_failure(exc: BaseException) -> str:
    """What a caller may be told about a failed TM1 call.

    TM1py's own messages carry the response body and every header the
    server sent; for a server the caller controls the address of, that
    is a way to read whatever answered. The detail goes to the log, the
    caller gets the shape of the failure.
    """

    if isinstance(exc, TM1pyRestException):
        return f"TM1 returned HTTP {exc.status_code} ({exc.reason})."

    if isinstance(exc, (TM1pyTimeout, asyncio.TimeoutError, requests.exceptions.Timeout)):
        return "The server did not respond in time."

    if isinstance(exc, TM1pyNetworkException):
        return (
            "The server could not be reached, or something in front of it "
            "answered instead."
        )

    return f"The server could not be reached ({type(exc).__name__})."


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
                _run_in_tm1_thread(func, *args, **kwargs),
                timeout=resolved_timeout + TIMEOUT_GRACE_SECONDS,
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
            # Full text (body and headers) to the log only.
            app_logger.warning(
                f"TM1 call {getattr(func, '__name__', func)!s} on connection "
                f"{connection_id} failed: {exc}"
            )

            if exc.status_code in (401, 403):
                raise TM1AuthenticationError(describe_failure(exc)) from exc

            if exc.status_code == 404:
                raise TM1NotFoundError(describe_failure(exc)) from exc

            if exc.status_code < TRANSIENT_STATUS_THRESHOLD:
                raise TM1ConnectionError(describe_failure(exc)) from exc

            last_exc = exc
        else:
            breaker.record_success()

            return result

        if attempt < resolved_max_retries:
            await asyncio.sleep(delay)
            delay *= 2

    breaker.record_failure()

    app_logger.warning(
        f"TM1 call {getattr(func, '__name__', func)!s} on connection "
        f"{connection_id} failed after {resolved_max_retries + 1} attempts: "
        f"{last_exc!r}"
    )

    raise TM1ConnectionError(
        f"TM1 request failed after {resolved_max_retries + 1} attempts: "
        f"{describe_failure(last_exc)}"
    ) from last_exc
