"""Encryption for stored connection credentials.

Two tables hold ciphertext produced here: `tm1_connections.
encrypted_password` and `planning_analytics_connections.
encrypted_credential`.

**Rotation is the reason this is not a bare `Fernet`.** A single key has
no safe way to change: the moment the key changes, every stored
ciphertext becomes undecryptable, and the only recovery is asking every
user to re-enter their TM1 password. That makes the key impossible to
rotate in response to a suspected exposure, which is exactly when
rotation is needed.

`MultiFernet` removes the trap. It encrypts with the first key and
decrypts with any of them, so an old key can stay readable while new
writes use the new one:

1. Set `TM1_CREDENTIALS_KEY` to the new key and
   `TM1_CREDENTIALS_KEY_PREVIOUS` to the old one. Deploy. Nothing
   breaks — old rows still decrypt, new writes use the new key.
2. Run `scripts/rotate_tm1_key.py` to re-encrypt every stored row.
3. Remove `TM1_CREDENTIALS_KEY_PREVIOUS`. The old key is now dead.

No downtime, and no step where a failure loses data — if the process
dies midway through step 2, the un-rotated rows still decrypt under the
previous key.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from src.core.config import settings
from src.tm1.exceptions import TM1ConnectionError

_fernet: MultiFernet | None = None


def _build_key(value: str, name: str) -> Fernet:
    try:
        return Fernet(value)
    except (ValueError, TypeError) as exc:
        raise TM1ConnectionError(f"{name} is not a valid Fernet key.") from exc


def _get_fernet() -> MultiFernet:
    global _fernet

    if _fernet is None:
        if not settings.TM1_CREDENTIALS_KEY:
            raise TM1ConnectionError(
                "TM1_CREDENTIALS_KEY is not configured. Generate one with "
                "Fernet.generate_key() and set it in the environment."
            )

        # Order is load-bearing: MultiFernet encrypts with the first key
        # and tries the rest only when decrypting. Putting the previous
        # key first would keep writing ciphertext under the key being
        # retired.
        keys = [_build_key(settings.TM1_CREDENTIALS_KEY, "TM1_CREDENTIALS_KEY")]

        if settings.TM1_CREDENTIALS_KEY_PREVIOUS:
            keys.append(
                _build_key(
                    settings.TM1_CREDENTIALS_KEY_PREVIOUS,
                    "TM1_CREDENTIALS_KEY_PREVIOUS",
                )
            )

        _fernet = MultiFernet(keys)

    return _fernet


def reset_cache() -> None:
    """Force the keys to be re-read.

    The rotation script changes settings in-process, and tests need the
    same. Nothing in request handling should call this.
    """

    global _fernet

    _fernet = None


def encrypt_password(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TM1ConnectionError(
            "Stored TM1 credentials could not be decrypted."
        ) from exc


def rotate_token(token: str) -> str:
    """Re-encrypt one ciphertext under the current primary key.

    `MultiFernet.rotate` decrypts with whichever key works and
    re-encrypts with the first, without the plaintext ever being
    returned to the caller — so a rotation script never holds a
    password in a variable it might log.
    """

    try:
        return _get_fernet().rotate(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TM1ConnectionError(
            "Stored TM1 credentials could not be decrypted. The key that "
            "encrypted them is not among the configured keys."
        ) from exc
