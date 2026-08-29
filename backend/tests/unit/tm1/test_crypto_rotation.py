"""Rotating the credential encryption key without losing credentials.

The property under test is that no step of a rotation can strand a
stored password. That matters because the alternative — a single key
that cannot change — means the key is unrotatable precisely when a
suspected exposure makes rotation necessary.
"""

import pytest
from cryptography.fernet import Fernet

from src.core.config import settings
from src.tm1 import crypto
from src.tm1.exceptions import TM1ConnectionError

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()
THIRD_KEY = Fernet.generate_key().decode()

PASSWORD = "tm1-service-account-p@ssw0rd"


@pytest.fixture(autouse=True)
def clean_key_cache():
    """The Fernet is process-global and cached.

    Without this a test that sets keys leaks them into the next one,
    and the failures depend on ordering.
    """

    crypto.reset_cache()
    yield
    crypto.reset_cache()


def configure(monkeypatch, current: str | None, previous: str | None = None):
    monkeypatch.setattr(settings, "TM1_CREDENTIALS_KEY", current)
    monkeypatch.setattr(settings, "TM1_CREDENTIALS_KEY_PREVIOUS", previous)
    crypto.reset_cache()


class TestSingleKey:

    def test_round_trip(self, monkeypatch):
        configure(monkeypatch, OLD_KEY)

        assert crypto.decrypt_password(crypto.encrypt_password(PASSWORD)) == PASSWORD

    def test_a_missing_key_is_a_readable_error(self, monkeypatch):
        configure(monkeypatch, None)

        with pytest.raises(TM1ConnectionError) as exc_info:
            crypto.encrypt_password(PASSWORD)

        assert "TM1_CREDENTIALS_KEY" in str(exc_info.value)

    def test_a_malformed_key_names_itself(self, monkeypatch):
        configure(monkeypatch, "not-a-fernet-key")

        with pytest.raises(TM1ConnectionError) as exc_info:
            crypto.encrypt_password(PASSWORD)

        assert "TM1_CREDENTIALS_KEY" in str(exc_info.value)

    def test_a_malformed_previous_key_is_named_distinctly(self, monkeypatch):
        """So the operator knows which of the two to fix."""

        configure(monkeypatch, OLD_KEY, previous="also-not-a-key")

        with pytest.raises(TM1ConnectionError) as exc_info:
            crypto.encrypt_password(PASSWORD)

        assert "TM1_CREDENTIALS_KEY_PREVIOUS" in str(exc_info.value)


class TestTheRotationWindow:
    """Step 1: both keys configured, nothing re-encrypted yet."""

    def test_credentials_written_under_the_old_key_still_decrypt(
        self, monkeypatch
    ):
        """The whole point. Deploying the new key must not break logins."""

        configure(monkeypatch, OLD_KEY)
        stored = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)

        assert crypto.decrypt_password(stored) == PASSWORD

    def test_new_writes_use_the_new_key(self, monkeypatch):
        """Order matters: MultiFernet encrypts with the first key.

        Reversed, the rotation would keep writing ciphertext under the
        key being retired and never finish.
        """

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)
        written = crypto.encrypt_password(PASSWORD)

        # Readable by the new key alone — so it was not written with the old.
        configure(monkeypatch, NEW_KEY)

        assert crypto.decrypt_password(written) == PASSWORD

    def test_the_old_key_alone_cannot_read_the_new_writes(self, monkeypatch):
        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)
        written = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, OLD_KEY)

        with pytest.raises(TM1ConnectionError):
            crypto.decrypt_password(written)


class TestRotateToken:

    def test_it_re_encrypts_under_the_new_key(self, monkeypatch):
        configure(monkeypatch, OLD_KEY)
        stored = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)
        rotated = crypto.rotate_token(stored)

        # Step 3: the old key is gone, and the rotated value still works.
        configure(monkeypatch, NEW_KEY)

        assert crypto.decrypt_password(rotated) == PASSWORD

    def test_the_ciphertext_actually_changes(self, monkeypatch):
        configure(monkeypatch, OLD_KEY)
        stored = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)

        assert crypto.rotate_token(stored) != stored

    def test_rotating_twice_is_harmless(self, monkeypatch):
        """The script is re-runnable after an interrupted rotation, so a
        row already on the new key must survive a second pass."""

        configure(monkeypatch, OLD_KEY)
        stored = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)
        once = crypto.rotate_token(stored)
        twice = crypto.rotate_token(once)

        configure(monkeypatch, NEW_KEY)

        assert crypto.decrypt_password(twice) == PASSWORD

    def test_an_unreadable_token_explains_itself(self, monkeypatch):
        """A row encrypted under a key nobody configured.

        The script reports and skips these rather than aborting, so the
        message has to say what is wrong.
        """

        configure(monkeypatch, THIRD_KEY)
        stranded = crypto.encrypt_password(PASSWORD)

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)

        with pytest.raises(TM1ConnectionError) as exc_info:
            crypto.rotate_token(stranded)

        assert "not among the configured keys" in str(exc_info.value)


class TestInterruptedRotation:

    def test_a_half_rotated_table_is_fully_readable(self, monkeypatch):
        """The safety property that makes the script interruptible.

        If it dies midway, some rows are on the new key and some on the
        old. Both must decrypt for the application to keep working.
        """

        configure(monkeypatch, OLD_KEY)
        original = [crypto.encrypt_password(f"{PASSWORD}-{index}") for index in range(4)]

        configure(monkeypatch, NEW_KEY, previous=OLD_KEY)

        # Two rows rotated, then the process dies.
        half_rotated = [crypto.rotate_token(token) for token in original[:2]]
        remaining = original[2:]

        for index, token in enumerate(half_rotated + remaining):
            assert crypto.decrypt_password(token) == f"{PASSWORD}-{index}"
