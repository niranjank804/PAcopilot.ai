from datetime import datetime, timedelta, timezone

import pytest

import src.services.auth_service as auth_service_module
from src.core.exceptions import AuthenticationException, PermissionDeniedException
from src.database.models.password_reset_token import PasswordResetToken
from src.repositories.password_reset_token_repository import (
    password_reset_token_repository,
)
from src.repositories.user_repository import user_repository
from src.schemas.auth import RefreshRequest
from src.services.auth_service import auth_service
from src.services.jwt_service import jwt_service
from tests.fixtures.factories import create_organization, create_user


class FakeEmailProvider:

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, *, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def fake_email_provider(monkeypatch):
    provider = FakeEmailProvider()
    monkeypatch.setattr(
        auth_service_module, "get_email_provider", lambda: provider
    )
    return provider


@pytest.mark.asyncio
async def test_refresh_issues_new_rotated_tokens(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    original_refresh_token = jwt_service.create_refresh_token(str(user.id))

    result = await auth_service.refresh(
        db_session, RefreshRequest(refresh_token=original_refresh_token)
    )

    assert result.access_token
    assert result.refresh_token
    assert result.refresh_token != original_refresh_token

    payload = jwt_service.decode_token(result.access_token)
    assert payload["sub"] == str(user.id)
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_refresh_rejects_garbage_token(db_session):
    with pytest.raises(AuthenticationException):
        await auth_service.refresh(
            db_session, RefreshRequest(refresh_token="not-a-real-token")
        )


@pytest.mark.asyncio
async def test_refresh_rejects_an_access_token(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    access_token = jwt_service.create_access_token(str(user.id))

    with pytest.raises(AuthenticationException):
        await auth_service.refresh(
            db_session, RefreshRequest(refresh_token=access_token)
        )


@pytest.mark.asyncio
async def test_refresh_rejects_inactive_user(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id, is_active=False)
    refresh_token = jwt_service.create_refresh_token(str(user.id))

    with pytest.raises(PermissionDeniedException):
        await auth_service.refresh(
            db_session, RefreshRequest(refresh_token=refresh_token)
        )


@pytest.mark.asyncio
async def test_request_password_reset_sends_email_with_link(
    db_session, fake_email_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await auth_service.request_password_reset(db_session, user.email)

    assert len(fake_email_provider.sent) == 1
    assert fake_email_provider.sent[0]["to"] == user.email
    assert "reset-password?token=" in fake_email_provider.sent[0]["body"]


@pytest.mark.asyncio
async def test_request_password_reset_is_a_silent_noop_for_unknown_email(
    db_session, fake_email_provider
):
    await auth_service.request_password_reset(db_session, "nobody@example.com")

    assert fake_email_provider.sent == []


@pytest.mark.asyncio
async def test_request_password_reset_is_a_silent_noop_for_inactive_user(
    db_session, fake_email_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id, is_active=False)

    await auth_service.request_password_reset(db_session, user.email)

    assert fake_email_provider.sent == []


@pytest.mark.asyncio
async def test_reset_password_with_valid_token_changes_password(
    db_session, fake_email_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    old_hash = user.password_hash

    await auth_service.request_password_reset(db_session, user.email)
    raw_token = fake_email_provider.sent[0]["body"].split("token=")[1].split()[0]

    await auth_service.reset_password(db_session, raw_token, "BrandNewPassword123!")

    refreshed = await user_repository.get_by_id(db_session, user.id)
    assert refreshed.password_hash != old_hash


@pytest.mark.asyncio
async def test_reset_password_rejects_garbage_token(db_session):
    with pytest.raises(AuthenticationException):
        await auth_service.reset_password(
            db_session, "not-a-real-token", "BrandNewPassword123!"
        )


@pytest.mark.asyncio
async def test_reset_password_rejects_already_used_token(
    db_session, fake_email_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await auth_service.request_password_reset(db_session, user.email)
    raw_token = fake_email_provider.sent[0]["body"].split("token=")[1].split()[0]

    await auth_service.reset_password(db_session, raw_token, "FirstNewPassword123!")

    with pytest.raises(AuthenticationException):
        await auth_service.reset_password(
            db_session, raw_token, "SecondNewPassword123!"
        )


@pytest.mark.asyncio
async def test_reset_password_rejects_expired_token(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    expired_token = PasswordResetToken(
        user_id=user.id,
        token_hash=auth_service_module._hash_reset_token("expired-raw-token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await password_reset_token_repository.create(db_session, expired_token)

    with pytest.raises(AuthenticationException):
        await auth_service.reset_password(
            db_session, "expired-raw-token", "BrandNewPassword123!"
        )


@pytest.fixture
def fake_google_claims(monkeypatch):
    claims: dict = {}

    def fake_verify(token: str) -> dict:
        return claims

    monkeypatch.setattr(auth_service_module, "verify_google_id_token", fake_verify)
    return claims


@pytest.mark.asyncio
async def test_google_login_issues_tokens_for_existing_active_user(
    db_session, fake_google_claims
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    fake_google_claims["email"] = user.email
    fake_google_claims["email_verified"] = True

    result = await auth_service.google_login(db_session, "fake-id-token")

    assert result.access_token
    payload = jwt_service.decode_token(result.access_token)
    assert payload["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_google_login_rejects_email_with_no_account(
    db_session, fake_google_claims
):
    fake_google_claims["email"] = "nobody@example.com"
    fake_google_claims["email_verified"] = True

    with pytest.raises(AuthenticationException):
        await auth_service.google_login(db_session, "fake-id-token")


@pytest.mark.asyncio
async def test_google_login_rejects_inactive_user(db_session, fake_google_claims):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id, is_active=False)
    fake_google_claims["email"] = user.email
    fake_google_claims["email_verified"] = True

    with pytest.raises(PermissionDeniedException):
        await auth_service.google_login(db_session, "fake-id-token")
