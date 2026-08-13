"""Trusted-proxy client-IP resolution.

Fixes a latent bug: `TRUSTED_PROXY_COUNT` existed in settings and was
never used. Every IP-keyed throttle read `request.client.host` directly,
which behind a reverse proxy is the *proxy's* address — so all clients
shared one bucket and the login / password-reset limits were a global
cap rather than a per-attacker one.
"""

import pytest

from src.core.config import settings
from src.core.rate_limit import client_ip_of


class FakeRequest:
    def __init__(self, headers: dict, peer: str | None):
        self.headers = headers
        self.client = type("C", (), {"host": peer})() if peer else None


class TestTrustedProxyResolution:

    def test_takes_the_entry_our_own_edge_added(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        # Our proxy appends the address it saw (9.9.9.9). Everything to
        # its left came from the client and is untrustworthy.
        request = FakeRequest(
            {"x-forwarded-for": "1.2.3.4, 9.9.9.9"}, "10.0.0.1"
        )

        assert client_ip_of(request) == "9.9.9.9"

    def test_a_forged_leftmost_entry_cannot_set_the_identity(self, monkeypatch):
        """The bypass this ordering prevents.

        Reading the leftmost entry — the common mistake — would let a
        caller send a new X-Forwarded-For per request and get a fresh
        rate-limit bucket every time, defeating the limiter entirely.
        """

        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        attacker = FakeRequest(
            {"x-forwarded-for": "evil-1, evil-2, evil-3, 9.9.9.9"}, "10.0.0.1"
        )

        # Whatever they invent, they always resolve to the same bucket.
        assert client_ip_of(attacker) == "9.9.9.9"

    def test_two_trusted_proxies(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)

        request = FakeRequest(
            {"x-forwarded-for": "1.2.3.4, 5.5.5.5, 9.9.9.9"}, "10.0.0.1"
        )

        assert client_ip_of(request) == "5.5.5.5"

    def test_zero_trusted_proxies_uses_the_peer(self, monkeypatch):
        """Correct when the app is directly exposed.

        With no proxy in front, the header is entirely client-supplied
        and must be ignored.
        """

        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)

        request = FakeRequest({"x-forwarded-for": "1.2.3.4"}, "10.0.0.1")

        assert client_ip_of(request) == "10.0.0.1"

    def test_fewer_hops_than_configured_does_not_index_off_the_end(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 3)

        request = FakeRequest({"x-forwarded-for": "9.9.9.9"}, "10.0.0.1")

        assert client_ip_of(request) == "9.9.9.9"

    def test_no_header_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        assert client_ip_of(FakeRequest({}, "10.0.0.1")) == "10.0.0.1"

    def test_no_peer_and_no_header_is_none(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        assert client_ip_of(FakeRequest({}, None)) is None

    @pytest.mark.parametrize(
        "header", ["", "   ", ",", " , , "]
    )
    def test_empty_or_malformed_headers_fall_back(self, monkeypatch, header):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        request = FakeRequest({"x-forwarded-for": header}, "10.0.0.1")

        assert client_ip_of(request) == "10.0.0.1"

    def test_whitespace_around_entries_is_stripped(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)

        request = FakeRequest(
            {"x-forwarded-for": "  1.2.3.4 ,   9.9.9.9   "}, "10.0.0.1"
        )

        assert client_ip_of(request) == "9.9.9.9"
