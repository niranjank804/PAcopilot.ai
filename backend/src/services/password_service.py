from passlib.context import CryptContext

from src.core.config import settings


class PasswordService:
    def __init__(self):
        self._pwd_context = CryptContext(
            schemes=[settings.PASSWORD_HASH_SCHEME],
            deprecated="auto",
        )

    def hash_password(self, password: str) -> str:
        return self._pwd_context.hash(password)

    def verify_password(
        self,
        plain_password: str,
        hashed_password: str,
    ) -> bool:
        return self._pwd_context.verify(
            plain_password,
            hashed_password,
        )


password_service = PasswordService()