"""Tolerating a backend that spins down.

Free hosting sleeps after ~15 minutes idle. The first request after that
gets a 502/503 from the edge while the app boots. Without this the
worker reports a healthy deployment as an outage, and every quiet period
produces a spurious failure.
"""

import pytest
import requests

from pa_worker.client.control_plane import (
    _COLD_START_ATTEMPTS,
    _COLD_START_STATUSES,
    ControlPlaneClient,
)
from pa_worker.errors import ControlPlaneError


class FakeSession:
    """Answers with a scripted sequence of statuses."""

    def __init__(self, statuses, body=None):
        self.statuses = list(statuses)
        self.body = body if body is not None else {"success": True, "data": {}}
        self.calls = 0
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls += 1
        status = (
            self.statuses.pop(0) if self.statuses else 200
        )

        response = requests.Response()
        response.status_code = status
        response._content = (
            b'{"success": true, "data": {"ok": 1}}'
            if status < 400
            else b'{"success": false, "error": {"code": "X", "message": "y"}}'
        )
        response.headers["Content-Type"] = "application/json"

        return response


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    # The backoff is real seconds in production; tests must not wait.
    monkeypatch.setattr("pa_worker.client.control_plane.time.sleep", lambda _: None)


def _client(session, config, credentials):
    # Credentials must be present: _ensure_token() checks them before it
    # looks at the cached token.
    client = ControlPlaneClient(config, credentials, session=session)
    # Pre-seed the token so these tests exercise transport only, not the
    # token exchange.
    client._token = "test-token"
    client._token_expires_at = float("inf")

    return client


class TestColdStartRecovery:

    @pytest.mark.parametrize("status", sorted(_COLD_START_STATUSES))
    def test_a_booting_backend_is_waited_out(self, status, config, credentials):
        # The exact sequence a spun-down host produces: the edge answers
        # while the app starts, then the app answers.
        session = FakeSession([status, status, 200])

        result = _client(session, config, credentials).claim_job()

        assert session.calls == 3
        assert result == {"ok": 1}

    def test_recovery_is_bounded(self, config, credentials):
        # A genuinely dead server must still fail, and quickly enough
        # that the poll loop is not hung.
        session = FakeSession([503] * 20)

        with pytest.raises(ControlPlaneError):
            _client(session, config, credentials).claim_job()

        assert session.calls <= _COLD_START_ATTEMPTS + 1

    def test_a_healthy_backend_is_not_retried(self, config, credentials):
        session = FakeSession([200])

        _client(session, config, credentials).claim_job()

        assert session.calls == 1


class TestWhatMustNotBeRetried:
    """Retrying the wrong thing is worse than failing."""

    def test_a_real_error_is_not_retried(self, config, credentials):
        # 409 means the app processed the request and refused it —
        # retrying would not change the answer.
        session = FakeSession([409])

        with pytest.raises(ControlPlaneError):
            _client(session, config, credentials).claim_job()

        assert session.calls == 1

    def test_a_read_timeout_is_not_retried(self, config, credentials):
        """The distinction that keeps `claim` safe.

        A 503 means the request never reached the app. A read timeout
        means it may well have been processed and only the response was
        lost — retrying `claim` there would take a second job while the
        first sat orphaned until its lease expired.
        """

        class TimingOutSession:
            calls = 0
            headers: dict = {}

            def request(self, *args, **kwargs):
                TimingOutSession.calls += 1

                raise requests.exceptions.ReadTimeout("read timed out")

        session = TimingOutSession()

        with pytest.raises(ControlPlaneError):
            _client(session, config, credentials).claim_job()

        assert session.calls == 1, "a read timeout must not be retried"

    def test_401_still_triggers_exactly_one_token_refresh(self, config, credentials):
        # The pre-existing behaviour must survive: one re-auth attempt,
        # not a loop.
        session = FakeSession([401, 401])

        client = ControlPlaneClient(config, credentials, session=session)
        client._token = "stale"
        client._token_expires_at = float("inf")

        with pytest.raises(Exception):
            client.claim_job()

        # Original + one retry after minting a fresh token. The token
        # mint itself also goes through the session.
        assert session.calls <= 4
