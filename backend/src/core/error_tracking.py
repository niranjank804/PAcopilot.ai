"""Optional error tracking. Inert unless a DSN is configured.

Today an unhandled exception is caught by `main.py`'s handler, logged,
and returned as a generic 500. Nothing aggregates it, so the only way to
learn a customer hit a bug is for them to say so.

Design constraints that shaped this:

* **No hard dependency.** `sentry-sdk` is not in requirements.txt. If it
  is absent, or no DSN is set, every function here is a no-op and the
  app behaves exactly as before. That keeps the deployment story
  unchanged for anyone who does not want a third-party error sink.

* **Scrubbing is on by default and is not the vendor's job.** This
  application handles TM1 passwords, OAuth tokens, worker credentials
  and report data. `send_default_pii=False` alone is not enough — it
  governs user identifiers, not arbitrary request bodies. `_scrub()`
  drops the values most likely to carry a secret before the event
  leaves the process.

* **Report data never goes.** A report artifact can contain a
  customer's financials. Request bodies are dropped wholesale rather
  than filtered, because a filter has to be right every time and a drop
  only has to be right once.
"""

from typing import Any

from src.core.config import settings
from src.core.logging import app_logger

_initialized = False

#: Header and context keys whose values are dropped before an event is
#: sent. Matched case-insensitively on substring, so `X-Auth-Token` and
#: `authorization` are both covered.
_SENSITIVE_KEYS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "credential",
    "x-workbook-checksum",
)


def _scrub(event: dict, hint: dict | None = None) -> dict | None:
    """Drop anything likely to carry a secret or customer data."""

    request = event.get("request")

    if isinstance(request, dict):
        # Bodies are dropped entirely: a report payload can contain a
        # customer's financials, and a selective filter has to be right
        # every time whereas a drop only has to be right once.
        request.pop("data", None)
        request.pop("cookies", None)

        headers = request.get("headers")

        if isinstance(headers, dict):
            for key in list(headers):
                if any(needle in key.lower() for needle in _SENSITIVE_KEYS):
                    headers[key] = "[redacted]"

        # A query string can carry a token in a badly-built URL.
        query = request.get("query_string")

        if query and any(
            needle in str(query).lower() for needle in _SENSITIVE_KEYS
        ):
            request["query_string"] = "[redacted]"

    for section in ("extra", "contexts", "tags"):
        block = event.get(section)

        if isinstance(block, dict):
            for key in list(block):
                if any(needle in key.lower() for needle in _SENSITIVE_KEYS):
                    block[key] = "[redacted]"

    return event


def initialize() -> bool:
    """Set up error tracking if configured. Returns whether it is active.

    Safe to call more than once and safe to call when nothing is
    configured — both are no-ops.
    """

    global _initialized

    if _initialized:
        return True

    dsn = getattr(settings, "SENTRY_DSN", None)

    if not dsn:
        # The ordinary case for a deployment that has not opted in.
        # Debug, not warning: this is a choice, not a problem.
        app_logger.debug("error tracking: no DSN configured, staying inert")

        return False

    try:
        import sentry_sdk
    except ImportError:
        # Configured but the package is missing. Worth a warning: the
        # operator believes errors are being captured and they are not.
        app_logger.warning(
            "error tracking: SENTRY_DSN is set but sentry-sdk is not "
            "installed; errors are NOT being captured."
        )

        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.ENVIRONMENT,
            release=settings.APP_VERSION,
            # Sampled, not everything: tracing every request on a free
            # tier is both expensive and useless.
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            # PII off, and scrubbing on top — see the module docstring
            # for why the flag alone is insufficient here.
            send_default_pii=False,
            before_send=_scrub,
        )

        _initialized = True

        app_logger.info(
            f"error tracking: active (environment={settings.ENVIRONMENT})"
        )

        return True
    except Exception as exc:  # noqa: BLE001
        # Never let telemetry setup stop the application booting.
        app_logger.error(
            f"error tracking: initialization failed ({type(exc).__name__})"
        )

        return False


def capture_exception(exc: BaseException, **context: Any) -> None:
    """Report an exception if tracking is active; otherwise do nothing."""

    if not _initialized:
        return

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                if any(needle in key.lower() for needle in _SENSITIVE_KEYS):
                    continue

                scope.set_tag(key, str(value)[:200])

            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        # Losing an error report must never itself raise.
        pass
