import uuid

import pytest
from jose import jwt

from src.core.config import settings
from src.core.exceptions import AuthenticationException
from src.reports.worker_credentials import (
    WORKER_TOKEN_TYPE,
    create_worker_token,
    decode_worker_token,
    generate_enrollment_token,
    generate_worker_secret,
    hash_secret,
    verify_secret,
)
from src.services.jwt_service import jwt_service


class TestSecretGeneration:

    def test_secrets_are_unique(self):
        secrets = {generate_worker_secret() for _ in range(100)}

        assert len(secrets) == 100

    def test_secrets_carry_an_identifying_prefix(self):
        # So a leaked value is recognisable in a log or by a scanner.
        assert generate_worker_secret().startswith("pacw-secret-")
        assert generate_enrollment_token().startswith("pacw-enroll-")

    def test_secrets_have_meaningful_entropy(self):
        # 32 url-safe bytes -> ~43 chars after the prefix.
        assert len(generate_worker_secret()) > 40


class TestSecretHashing:

    def test_hash_is_not_the_secret(self):
        secret = generate_worker_secret()

        assert hash_secret(secret) != secret
        assert secret not in hash_secret(secret)

    def test_hash_is_deterministic(self):
        secret = generate_worker_secret()

        assert hash_secret(secret) == hash_secret(secret)

    def test_verify_accepts_the_right_secret(self):
        secret = generate_worker_secret()

        assert verify_secret(secret, hash_secret(secret))

    def test_verify_rejects_a_wrong_secret(self):
        assert not verify_secret(
            generate_worker_secret(), hash_secret(generate_worker_secret())
        )

    def test_verify_rejects_a_missing_hash(self):
        # A worker row with no credential (created but never enrolled, or
        # reset) must not authenticate anything.
        assert not verify_secret(generate_worker_secret(), None)
        assert not verify_secret(generate_worker_secret(), "")

    def test_hash_is_keyed_by_the_application_secret(self):
        secret = generate_worker_secret()
        original = hash_secret(secret)

        previous_key = settings.SECRET_KEY
        settings.SECRET_KEY = "a-different-secret-key-of-sufficient-length!!"

        try:
            # Keyed, so a database dump alone is not enough to verify
            # guesses offline.
            assert hash_secret(secret) != original
        finally:
            settings.SECRET_KEY = previous_key


class TestWorkerTokens:

    def test_round_trip(self):
        worker_id = uuid.uuid4()
        organization_id = uuid.uuid4()

        token, expires_in = create_worker_token(
            worker_id=worker_id,
            organization_id=organization_id,
            secret_version=3,
        )

        payload = decode_worker_token(token)

        assert payload["sub"] == str(worker_id)
        assert payload["org"] == str(organization_id)
        assert payload["sv"] == 3
        assert payload["type"] == WORKER_TOKEN_TYPE
        assert expires_in > 0

    def test_token_lifetime_is_short(self):
        _, expires_in = create_worker_token(
            worker_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            secret_version=1,
        )

        # A stolen token should be useful for minutes, not for the life
        # of the deployment the way a static API key would be.
        assert expires_in <= 3600

    def test_a_user_access_token_is_rejected(self):
        # Both token families are signed with the same key, so the type
        # claim is the only thing separating them. Without this check a
        # stolen worker credential would work against the whole
        # user-facing API.
        user_token = jwt_service.create_access_token(str(uuid.uuid4()))

        with pytest.raises(AuthenticationException):
            decode_worker_token(user_token)

    def test_a_worker_token_is_not_a_user_access_token(self):
        token, _ = create_worker_token(
            worker_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            secret_version=1,
        )

        payload = jwt_service.decode_token(token)

        # get_current_user requires type == "access"; this is not that.
        assert payload["type"] != "access"

    def test_a_token_signed_with_another_key_is_rejected(self):
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": WORKER_TOKEN_TYPE,
                "org": str(uuid.uuid4()),
                "sv": 1,
            },
            "an-attacker-controlled-key-of-length-32+",
            algorithm="HS256",
        )

        with pytest.raises(AuthenticationException):
            decode_worker_token(forged)

    @pytest.mark.parametrize(
        "garbage", ["", "not.a.token", "Bearer x", "a" * 500]
    )
    def test_malformed_tokens_are_rejected_cleanly(self, garbage):
        with pytest.raises(AuthenticationException):
            decode_worker_token(garbage)

    def test_expired_token_is_rejected(self):
        expired = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": WORKER_TOKEN_TYPE,
                "org": str(uuid.uuid4()),
                "sv": 1,
                "exp": 1000000000,  # 2001
            },
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        with pytest.raises(AuthenticationException):
            decode_worker_token(expired)
