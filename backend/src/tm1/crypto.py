from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings
from src.tm1.exceptions import TM1ConnectionError

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet

    if _fernet is None:
        if not settings.TM1_CREDENTIALS_KEY:
            raise TM1ConnectionError(
                "TM1_CREDENTIALS_KEY is not configured. Generate one with "
                "Fernet.generate_key() and set it in the environment."
            )

        try:
            _fernet = Fernet(settings.TM1_CREDENTIALS_KEY)
        except ValueError as exc:
            raise TM1ConnectionError(
                "TM1_CREDENTIALS_KEY is not a valid Fernet key."
            ) from exc

    return _fernet


def encrypt_password(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TM1ConnectionError(
            "Stored TM1 credentials could not be decrypted."
        ) from exc
