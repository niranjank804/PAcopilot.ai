from unittest.mock import patch

import pytest

from src.core.config import settings
from src.core.exceptions import AuthenticationException
from src.services.google_oauth import verify_google_id_token


@pytest.fixture
def google_client_id():
    original = settings.GOOGLE_OAUTH_CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    yield
    settings.GOOGLE_OAUTH_CLIENT_ID = original


def test_verify_google_id_token_rejects_when_not_configured():
    original = settings.GOOGLE_OAUTH_CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_ID = None
    try:
        with pytest.raises(AuthenticationException):
            verify_google_id_token("some-token")
    finally:
        settings.GOOGLE_OAUTH_CLIENT_ID = original


def test_verify_google_id_token_returns_claims_on_success(google_client_id):
    with patch(
        "src.services.google_oauth.google_id_token.verify_oauth2_token",
        return_value={"email": "a@example.com", "email_verified": True},
    ):
        claims = verify_google_id_token("valid-token")

    assert claims["email"] == "a@example.com"


def test_verify_google_id_token_rejects_invalid_token(google_client_id):
    with patch(
        "src.services.google_oauth.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token expired"),
    ):
        with pytest.raises(AuthenticationException):
            verify_google_id_token("expired-token")


def test_verify_google_id_token_rejects_unverified_email(google_client_id):
    with patch(
        "src.services.google_oauth.google_id_token.verify_oauth2_token",
        return_value={"email": "a@example.com", "email_verified": False},
    ):
        with pytest.raises(AuthenticationException):
            verify_google_id_token("valid-token-unverified-email")
