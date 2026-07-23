"""Fixtures shared by tests/live/*.

Every test here talks to a real TM1 server, configured entirely through
environment variables (never hardcoded, never accepted as chat input):

    TM1_ADDRESS   (required)
    TM1_USER      (required)
    TM1_PASSWORD  (required)
    TM1_PORT      (optional, default 8010)
    TM1_SSL       (optional, default true)
    TM1_NAMESPACE (optional — accepted for forward-compat; NOT yet wired
                   through connection_manager.py, so CAM auth cannot
                   actually be exercised yet. See docs/live_validation/.)

If the required variables aren't set, every test in this package is
skipped (not failed) — safe to run `pytest` here with nothing configured.
"""

import os

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user

pytestmark = pytest.mark.live


def _require_env(name: str) -> str:
    value = os.environ.get(name)

    if not value:
        pytest.skip(f"{name} not set — skipping live TM1 validation test")

    return value


@pytest.fixture
def live_tm1_config() -> dict:
    return {
        "address": _require_env("TM1_ADDRESS"),
        "port": int(os.environ.get("TM1_PORT", "8010")),
        "ssl": os.environ.get("TM1_SSL", "true").strip().lower() == "true",
        "username": _require_env("TM1_USER"),
        "password": _require_env("TM1_PASSWORD"),
        "namespace": os.environ.get("TM1_NAMESPACE"),
    }


@pytest.fixture
def live_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
async def live_connection(db_session, live_credentials_key, live_tm1_config):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Live Validation",
        address=live_tm1_config["address"],
        port=live_tm1_config["port"],
        ssl=live_tm1_config["ssl"],
        username=live_tm1_config["username"],
        password=live_tm1_config["password"],
    )

    return org, user, connection
