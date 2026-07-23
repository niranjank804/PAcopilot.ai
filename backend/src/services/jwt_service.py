import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from src.core.config import settings


class JWTService:
    def create_access_token(self, subject: str) -> str:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

        payload = {
            "sub": subject,
            "type": "access",
            "exp": expire,
            "jti": str(uuid.uuid4()),
        }

        return jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def create_refresh_token(self, subject: str) -> str:
        expire = datetime.now(UTC) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        payload = {
            "sub": subject,
            "type": "refresh",
            "exp": expire,
            "jti": str(uuid.uuid4()),
        }

        return jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def decode_token(self, token: str) -> dict:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )


jwt_service = JWTService()
