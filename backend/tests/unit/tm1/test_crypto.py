import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.crypto import decrypt_password, encrypt_password
from src.tm1.exceptions import TM1ConnectionError


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def test_encrypt_decrypt_round_trips(tm1_credentials_key):
    token = encrypt_password("super-secret-password")

    assert token != "super-secret-password"
    assert decrypt_password(token) == "super-secret-password"


def test_encrypt_raises_when_key_unconfigured():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = None
    crypto_module._fernet = None

    try:
        with pytest.raises(TM1ConnectionError):
            encrypt_password("secret")
    finally:
        settings.TM1_CREDENTIALS_KEY = original
        crypto_module._fernet = None


def test_decrypt_raises_on_invalid_token(tm1_credentials_key):
    with pytest.raises(TM1ConnectionError):
        decrypt_password("not-a-real-token")
