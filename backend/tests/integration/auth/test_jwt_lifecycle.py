"""JWT revocation, rotation and reuse detection.

A JWT validates itself from signature and expiry alone, so without these
mechanisms "log out" only clears the browser and a leaked refresh token
stays usable for its full seven days.
"""

import pytest

from tests.fixtures.factories import DEFAULT_PASSWORD, create_organization, create_user


async def _login(client, db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        json={"username": user.username, "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 200, response.text
    tokens = response.json()["data"]

    return user, tokens


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ---------------------------------------------------------------------------
# Logout.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_is_dead_after_logout(client, db_session):
    user, tokens = await _login(client, db_session)

    logout = await client.post(
        "/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=_auth(tokens),
    )
    assert logout.status_code == 200

    refreshed = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_logout_is_idempotent(client, db_session):
    user, tokens = await _login(client, db_session)

    body = {"refresh_token": tokens["refresh_token"]}

    assert (await client.post("/auth/logout", json=body, headers=_auth(tokens))).status_code == 200
    assert (await client.post("/auth/logout", json=body, headers=_auth(tokens))).status_code == 200


@pytest.mark.asyncio
async def test_logout_all_kills_the_access_token_too(client, db_session):
    user, tokens = await _login(client, db_session)

    assert (await client.get("/auth/me", headers=_auth(tokens))).status_code == 200

    assert (
        await client.post("/auth/logout-all", headers=_auth(tokens))
    ).status_code == 200

    # Bulk revocation applies to tokens already issued, not just refreshes.
    assert (await client.get("/auth/me", headers=_auth(tokens))).status_code == 401


# ---------------------------------------------------------------------------
# Rotation and reuse detection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_rotates_the_token(client, db_session):
    user, tokens = await _login(client, db_session)

    response = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 200

    rotated = response.json()["data"]["refresh_token"]

    assert rotated != tokens["refresh_token"]


@pytest.mark.asyncio
async def test_a_spent_refresh_token_cannot_be_reused(client, db_session):
    user, tokens = await _login(client, db_session)

    first = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_reuse_of_a_spent_token_ends_every_session(client, db_session):
    """A replay means the token was copied — the live session dies too.

    There is no way to tell the thief from the legitimate client, so the
    safe reading is compromise.
    """

    user, tokens = await _login(client, db_session)

    rotated = (
        await client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).json()["data"]

    # Replay the spent token.
    await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    # The token issued by the legitimate rotation is now dead as well.
    after = await client.post(
        "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )

    assert after.status_code == 401


# ---------------------------------------------------------------------------
# Password reset ends every session.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_invalidates_existing_sessions(
    client, db_session
):
    from datetime import datetime, timedelta, timezone

    from src.database.models.password_reset_token import PasswordResetToken
    from src.services.auth_service import _hash_reset_token

    user, tokens = await _login(client, db_session)

    raw = "reset-token-value"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    await db_session.flush()

    response = await client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "An0therStr0ngPass!"},
    )
    assert response.status_code == 200, response.text

    assert (await client.get("/auth/me", headers=_auth(tokens))).status_code == 401


# ---------------------------------------------------------------------------
# Backward compatibility.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_token_without_iat_is_still_accepted(client, db_session):
    """Tokens minted before this feature shipped must not be rejected.

    Deploying revocation must not sign the whole user base out.
    """

    from src.services.token_revocation_service import token_revocation_service
    from datetime import datetime, timezone

    assert not token_revocation_service.issued_before_cutoff(
        {"sub": "x"}, datetime.now(timezone.utc)
    )
