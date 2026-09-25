"""Planning Analytics on Cloud with an IBM non-interactive account.

These accounts sign in through IBM's gateway at /tm1/api/<database>/ with
the LDAP CAM namespace. A basic login — what a "native" connection sends —
is refused, which is why they could not connect before.

The TM1py test below builds a real RestService with the kwargs PA-Copilot
produces, stopping only the network call, and checks the URL and the
Authorization header TM1py would actually send.
"""

import base64
import uuid

import pytest
import requests
from TM1py.Services.RestService import RestService

from src.core.exceptions import ValidationException
from src.database.models.tm1_connection import TM1Connection
from src.tm1.addressing import parse_address
from src.tm1.client.connection_manager import build_tm1_kwargs
from src.tm1.service import _check_pa_cloud, _explain


def _connection(**overrides) -> TM1Connection:
    values = dict(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="PA on Cloud",
        address="mycompany.planning-analytics.ibmcloud.com",
        port=443,
        ssl=True,
        username="mycompany_tm1_automation",
        encrypted_password=b"",
        authentication_type="pa_cloud",
        tenant=None,
        database="Planning Sample",
    )
    values.update(overrides)
    return TM1Connection(**values)


def test_kwargs_use_the_gateway_path_and_ldap_namespace():
    kwargs = build_tm1_kwargs(_connection(), "secret")

    assert kwargs["base_url"] == (
        "https://mycompany.planning-analytics.ibmcloud.com/tm1/api/Planning Sample/"
    )
    assert kwargs["namespace"] == "LDAP"
    assert kwargs["user"] == "mycompany_tm1_automation"
    assert kwargs["password"] == "secret"
    assert kwargs["ssl"] is True and kwargs["verify"] is True
    assert kwargs["async_requests_mode"] is True
    assert kwargs["cancel_at_timeout"] is True


def test_a_pasted_url_is_reduced_to_the_host():
    kwargs = build_tm1_kwargs(
        _connection(address="https://mycompany.planning-analytics.ibmcloud.com/"),
        "secret",
    )

    assert "//tm1" not in kwargs["base_url"].replace("https://", "")


class _Stop(Exception):
    pass


def test_tm1py_signs_in_with_cam_on_the_gateway_url(monkeypatch):
    """TM1py's real sign-in, stopped at the wire: the first request it
    sends must go to the gateway path and carry a CAMNamespace header."""

    sent: dict = {}

    def capture(self, *args, **kwargs):
        sent["url"] = kwargs.get("url") or (args[0] if args else None)
        sent["headers"] = dict(kwargs.get("headers") or {})
        raise _Stop()

    monkeypatch.setattr(requests.Session, "get", capture)

    with pytest.raises(_Stop):
        RestService(**build_tm1_kwargs(_connection(), "secret"))

    assert sent["url"].startswith(
        "https://mycompany.planning-analytics.ibmcloud.com/tm1/api/Planning Sample/api/v1/"
    )
    assert sent["headers"]["Authorization"] == "CAMNamespace " + base64.b64encode(
        b"mycompany_tm1_automation:secret:LDAP"
    ).decode()


def test_the_rest_url_yields_the_database():
    parsed = parse_address(
        "https://mycompany.planning-analytics.ibmcloud.com/tm1/api/Planning Sample/api/v1/Cubes"
    )

    assert parsed.host == "mycompany.planning-analytics.ibmcloud.com"
    assert parsed.database == "Planning Sample"


@pytest.mark.parametrize(
    "database, username",
    [(None, "svc"), ("", "svc"), ("db", None), ("db", "apikey")],
)
def test_database_and_account_are_required(database, username):
    with pytest.raises(ValidationException):
        _check_pa_cloud("pa_cloud", database, username)


def test_other_types_are_not_checked():
    _check_pa_cloud("native", None, None)


def test_failures_name_the_part_to_fix():
    connection = _connection()

    assert "non-interactive account" in _explain("credentials_rejected", connection)
    assert "Planning Sample" in _explain("not_found", connection)
    assert "ibmcloud.com" in _explain("unreachable", connection)


# ----------------------------------------------------------------------
# Saved exactly as a TM1 tool's .env writes it: TM1_BASE_URL.
# ----------------------------------------------------------------------

BASE_URL = "https://assurantdev.planning-analytics.ibmcloud.com/tm1/api/AssurantGFSDev"


@pytest.fixture
def tm1_credentials_key():
    from cryptography.fernet import Fernet

    import src.tm1.crypto as crypto_module
    from src.core.config import settings

    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.mark.asyncio
async def test_a_base_url_saves_as_host_and_database(db_session, tm1_credentials_key):
    from src.tm1.service import tm1_integration_service
    from tests.fixtures.factories import create_organization, create_user

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="GFS Dev",
        address=BASE_URL,
        port=443,
        ssl=True,
        username="svc_account",
        password="secret",
        authentication_type="pa_cloud",
        database="",
    )

    assert connection.address == "assurantdev.planning-analytics.ibmcloud.com"
    assert connection.database == "AssurantGFSDev"

    kwargs = build_tm1_kwargs(connection, "secret")
    # The URL TM1py is given is the one the .env holds.
    assert kwargs["base_url"].rstrip("/") == BASE_URL
