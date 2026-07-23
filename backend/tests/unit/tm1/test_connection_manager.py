import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from TM1py.Exceptions import TM1pyNetworkException, TM1pyRestException

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.models.tm1_connection import TM1Connection
from src.tm1.client.connection_manager import TM1ConnectionManager
from src.tm1.crypto import encrypt_password
from src.tm1.exceptions import TM1AuthenticationError, TM1ConnectionError


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def _make_connection(tm1_credentials_key) -> TM1Connection:
    return TM1Connection(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="Test",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        encrypted_password=encrypt_password("secret"),
    )


@pytest.mark.asyncio
async def test_get_client_translates_auth_error(tm1_credentials_key):
    connection = _make_connection(tm1_credentials_key)
    manager = TM1ConnectionManager()

    with patch(
        "src.tm1.client.connection_manager.TM1Service",
        side_effect=TM1pyRestException(
            response="unauthorized", status_code=401, reason="Unauthorized", headers={}
        ),
    ):
        with pytest.raises(TM1AuthenticationError):
            await manager.get_client(connection)


@pytest.mark.asyncio
async def test_get_client_translates_network_error(tm1_credentials_key, monkeypatch):
    # get_client -> _connect always retries transient failures at the default
    # backoff; speed the sleep up so this test doesn't take 1s+2s+4s for real.
    monkeypatch.setattr(
        "src.tm1.resilience.asyncio.sleep",
        AsyncMock(return_value=None),
    )

    connection = _make_connection(tm1_credentials_key)
    manager = TM1ConnectionManager()

    with patch(
        "src.tm1.client.connection_manager.TM1Service",
        side_effect=TM1pyNetworkException(
            response="connection refused",
            status_code=0,
            reason="Network Error",
            headers={},
        ),
    ):
        with pytest.raises(TM1ConnectionError):
            await manager.get_client(connection)


@pytest.mark.asyncio
async def test_get_client_caches_by_connection_id(tm1_credentials_key):
    connection = _make_connection(tm1_credentials_key)
    manager = TM1ConnectionManager()

    fake_client = object()

    with patch(
        "src.tm1.client.connection_manager.TM1Service",
        return_value=fake_client,
    ) as mock_service:
        first = await manager.get_client(connection)
        second = await manager.get_client(connection)

    assert first is fake_client
    assert second is fake_client
    assert mock_service.call_count == 1


def test_invalidate_removes_cached_client(tm1_credentials_key):
    connection = _make_connection(tm1_credentials_key)
    manager = TM1ConnectionManager()
    manager._clients[connection.id] = object()

    manager.invalidate(connection.id)

    assert connection.id not in manager._clients


def test_build_tm1_kwargs_native_mode():
    from src.tm1.client.connection_manager import build_tm1_kwargs

    connection = MagicMock()
    connection.authentication_type = "native"
    connection.address = "tm1.example.com"
    connection.port = 8010
    connection.ssl = True
    connection.username = "admin"

    kwargs = build_tm1_kwargs(connection, "secret")

    assert kwargs == {
        "address": "tm1.example.com",
        "port": 8010,
        "ssl": True,
        "user": "admin",
        "password": "secret",
    }


def test_build_tm1_kwargs_v12_saas_mode():
    from src.tm1.client.connection_manager import build_tm1_kwargs

    connection = MagicMock()
    connection.authentication_type = "v12_saas"
    connection.address = "us-east-1.planninganalytics.saas.ibm.com"
    connection.tenant = "TENANT123"
    connection.database = "MyDatabase"

    kwargs = build_tm1_kwargs(connection, "api-key-value")

    # base_url-only form: passing tenant/database as kwargs routes TM1py's
    # auth detection into the CPD branch (demands cpd_url) - defect #002.
    assert kwargs == {
        "base_url": (
            "https://us-east-1.planninganalytics.saas.ibm.com"
            "/api/TENANT123/v0/tm1/MyDatabase/"
        ),
        "user": "apikey",
        "password": "api-key-value",
        "ssl": True,
        "verify": True,
    }
