import uuid
from datetime import UTC, datetime, timedelta

from jose import jwt

from src.core.config import settings


class JWTService:
    def create_access_token(self, subject: str) -> str:
        issued_at = datetime.now(UTC)
        expire = issued_at + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

        # `iat` is what makes bulk revocation possible: a password change
        # sets users.tokens_valid_from, and every token stamped before that
        # instant is rejected without the server having stored it.
        payload = {
            "sub": subject,
            "type": "access",
            "exp": expire,
            "iat": issued_at,
            "jti": str(uuid.uuid4()),
        }

        return jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def create_refresh_token(self, subject: str) -> str:
        issued_at = datetime.now(UTC)
        expire = issued_at + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        payload = {
            "sub": subject,
            "type": "refresh",
            "exp": expire,
            "iat": issued_at,
            "jti": str(uuid.uuid4()),
        }

        return jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def expiry_of(self, payload: dict) -> datetime:
        """The token's own expiry, for pruning its revocation row."""

        return datetime.fromtimestamp(int(payload["exp"]), tz=UTC)

    def decode_token(self, token: str) -> dict:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )


jwt_service = JWTService()
