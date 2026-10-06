import uuid

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.gateway.relay import MemoryBroker, set_broker
from tests.fixtures.factories import auth_headers, create_org_admin, create_user


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
def broker():
    b = MemoryBroker()
    set_broker(b)
    yield b
    set_broker(None)


@pytest.fixture(autouse=True)
def hosted_policy(monkeypatch):
    # As deployed: private TM1 addresses refused unless through a gateway.
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", False)


async def _create_gateway(client, headers, name="Head office"):
    resp = await client.post("/tm1/gateways", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _connection(address="192.168.1.17", **extra):
    return {
        "name": "On-prem", "address": address, "port": 8010, "ssl": True,
        "username": "admin", "password": "apple", **extra,
    }


@pytest.mark.asyncio
async def test_an_admin_creates_a_gateway_and_sees_its_key_once(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    created = await _create_gateway(client, headers)
    assert created["key"].startswith("pagw_")
    assert created["server_url"]
    assert created["gateway"]["online"] is False

    listed = (await client.get("/tm1/gateways", headers=headers)).json()["data"]
    assert [g["name"] for g in listed] == ["Head office"]
    assert "key" not in listed[0]


@pytest.mark.asyncio
async def test_only_tm1_write_may_create_a_gateway(client, db_session):
    org, _ = await create_org_admin(db_session)
    viewer = await create_user(db_session, org.id)

    resp = await client.post("/tm1/gateways", json={"name": "x"}, headers=auth_headers(viewer))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_gateway_polls_with_its_key_and_is_then_online(client, db_session, broker):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    created = await _create_gateway(client, headers)
    key = created["key"]

    bad = await client.post("/gateway/poll", json={"wait": 1},
                            headers={"Authorization": "Bearer pagw_nonsense"})
    assert bad.status_code == 401

    idle = await client.post("/gateway/poll", json={"wait": 1, "version": "1.0.0", "hostname": "TM1SRV"},
                             headers={"Authorization": f"Bearer {key}"})
    assert idle.status_code == 204

    listed = (await client.get("/tm1/gateways", headers=headers)).json()["data"][0]
    assert listed["online"] is True
    assert listed["hostname"] == "TM1SRV"


@pytest.mark.asyncio
async def test_requests_reach_the_gateway_and_answers_come_back(client, db_session, broker):
    org, admin = await create_org_admin(db_session)
    created = await _create_gateway(client, auth_headers(admin))
    gateway_id, key = created["gateway"]["id"], created["key"]
    gw = {"Authorization": f"Bearer {key}"}

    broker.push_request(gateway_id, {"id": "req-00000001", "method": "GET", "url": "https://tm1:8010/x"})
    polled = await client.post("/gateway/poll", json={"wait": 1}, headers=gw)
    assert polled.status_code == 200
    assert polled.json()["request"]["id"] == "req-00000001"

    answered = await client.post(
        "/gateway/answer",
        json={"id": "req-00000001", "index": 0, "parts": 1, "data": "", "status": 200},
        headers=gw,
    )
    assert answered.status_code == 200
    assert broker.pop_answer("req-00000001", 1)[0]["status"] == 200


@pytest.mark.asyncio
async def test_a_rotated_key_replaces_the_old_one(client, db_session, broker):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    created = await _create_gateway(client, headers)

    rotated = await client.post(f"/tm1/gateways/{created['gateway']['id']}/rotate-key", headers=headers)
    new_key = rotated.json()["data"]["key"]
    assert new_key != created["key"]

    old = await client.post("/gateway/poll", json={"wait": 1}, headers={"Authorization": f"Bearer {created['key']}"})
    new = await client.post("/gateway/poll", json={"wait": 1}, headers={"Authorization": f"Bearer {new_key}"})
    assert (old.status_code, new.status_code) == (401, 204)


@pytest.mark.asyncio
async def test_a_private_address_is_refused_without_a_gateway(client, db_session, tm1_credentials_key):
    _, admin = await create_org_admin(db_session)

    direct = await client.post("/tm1/connections", json=_connection(), headers=auth_headers(admin))
    assert direct.status_code in (400, 422)


@pytest.mark.asyncio
async def test_a_private_address_is_allowed_through_a_gateway(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    gateway = (await _create_gateway(client, headers))["gateway"]
    via = await client.post("/tm1/connections", json=_connection(gateway_id=gateway["id"]), headers=headers)
    assert via.status_code == 201, via.text
    assert via.json()["data"]["gateway_id"] == gateway["id"]

    listed = (await client.get("/tm1/gateways", headers=headers)).json()["data"][0]
    assert listed["connection_count"] == 1

    # In use: the gateway cannot be removed from under its connection.
    blocked = await client.delete(f"/tm1/gateways/{gateway['id']}", headers=headers)
    assert blocked.status_code in (400, 422)


@pytest.mark.asyncio
async def test_a_connection_cannot_use_another_organizations_gateway(client, db_session, tm1_credentials_key):
    _, admin_a = await create_org_admin(db_session)
    _, admin_b = await create_org_admin(db_session)
    foreign = (await _create_gateway(client, auth_headers(admin_a)))["gateway"]

    resp = await client.post("/tm1/connections", json=_connection(gateway_id=foreign["id"]),
                             headers=auth_headers(admin_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_only_native_connections_go_through_a_gateway(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    gateway = (await _create_gateway(client, headers))["gateway"]

    resp = await client.post(
        "/tm1/connections",
        json=_connection(address="acme.planning-analytics.ibmcloud.com", authentication_type="pa_cloud",
                         database="Prod", gateway_id=gateway["id"]),
        headers=headers,
    )
    assert resp.status_code in (400, 422)
    assert "gateway" in resp.text.lower()


@pytest.mark.asyncio
async def test_a_connection_can_move_off_its_gateway_to_a_public_address(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    gateway = (await _create_gateway(client, headers))["gateway"]
    conn = (await client.post("/tm1/connections", json=_connection(gateway_id=gateway["id"]),
                              headers=headers)).json()["data"]

    public = await client.patch(
        f"/tm1/connections/{conn['id']}",
        json={"gateway_id": None, "address": "tm1.example.com", "password": "again"},
        headers=headers,
    )
    assert public.status_code == 200, public.text
    assert public.json()["data"]["gateway_id"] is None

    # Now unused, the gateway can be removed.
    assert (await client.delete(f"/tm1/gateways/{gateway['id']}", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_moving_off_the_gateway_keeps_a_private_address_refused(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    gateway = (await _create_gateway(client, headers))["gateway"]
    conn = (await client.post("/tm1/connections", json=_connection(gateway_id=gateway["id"]),
                              headers=headers)).json()["data"]

    off = await client.patch(f"/tm1/connections/{conn['id']}", json={"gateway_id": None}, headers=headers)
    assert off.status_code in (400, 422)  # 192.168.1.17 is not reachable directly


def test_the_key_format_carries_id_and_version():
    from src.tm1.gateway.service import _new_key

    gid = uuid.uuid4()
    key = _new_key(gid, 3)
    assert key.startswith(f"pagw_{gid.hex}.3.")
