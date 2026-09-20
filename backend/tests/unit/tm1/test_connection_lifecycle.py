"""A TM1 session has a timeout on the way in and a logout on the way out.

TM1py was built without a timeout, so a server that stopped answering
kept the thread forever; and a dropped client kept its session open
until TM1 expired it.
"""

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.models.tm1_connection import TM1Connection
from src.tm1.client.connection_manager import (
    TM1ConnectionManager,
    build_tm1_kwargs,
)
from src.tm1.crypto import encrypt_password


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def _native() -> TM1Connection:
    return TM1Connection(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="On-prem",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        encrypted_password=b"",
        authentication_type="native",
    )


def _saas() -> TM1Connection:
    return TM1Connection(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="SaaS",
        address="us-east-1.planninganalytics.saas.ibm.com",
        port=443,
        ssl=True,
        username="apikey",
        encrypted_password=b"",
        authentication_type="v12_saas",
        tenant="TENANT",
        database="db",
    )


@pytest.mark.parametrize("connection", [_native(), _saas()])
def test_every_client_is_built_with_a_request_timeout(connection, monkeypatch):
    monkeypatch.setattr(settings, "TM1_REQUEST_TIMEOUT_SECONDS", 12.5)

    kwargs = build_tm1_kwargs(connection, "secret")

    assert kwargs["timeout"] == 12.5
    # And TM1 is told to stop the work it was doing for us.
    assert kwargs["cancel_at_timeout"] is True


@pytest.mark.asyncio
async def test_invalidate_logs_the_dropped_session_out(tm1_credentials_key):
    manager = TM1ConnectionManager()
    connection = _native()
    connection.encrypted_password = encrypt_password("secret")
    client = MagicMock()
    manager._clients[connection.id] = client

    manager.invalidate(connection.id)

    # Logout runs on a worker thread so the caller does not wait on TM1.
    await asyncio.sleep(0.05)

    assert connection.id not in manager._clients
    client.logout.assert_called_once()


@pytest.mark.asyncio
async def test_a_logout_the_server_refuses_is_not_an_error():
    manager = TM1ConnectionManager()
    connection_id = uuid.uuid4()
    client = MagicMock()
    client.logout.side_effect = RuntimeError("session already gone")
    manager._clients[connection_id] = client

    manager.invalidate(connection_id)
    await asyncio.sleep(0.05)

    client.logout.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_ends_every_cached_session():
    manager = TM1ConnectionManager()
    clients = [MagicMock(), MagicMock()]

    for client in clients:
        manager._clients[uuid.uuid4()] = client

    await manager.shutdown()

    assert manager._clients == {}

    for client in clients:
        client.logout.assert_called_once()
