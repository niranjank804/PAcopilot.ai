import pytest

from tests.fixtures.factories import auth_headers, create_org_admin, create_user


@pytest.mark.asyncio
async def test_get_usage_summary_returns_envelope(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.get("/monitoring/usage", headers=headers)

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "total_requests" in body
    assert "by_model" in body


@pytest.mark.asyncio
async def test_get_tool_summary_returns_envelope(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.get("/monitoring/tools", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_get_tm1_status_returns_envelope(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.get("/monitoring/tm1-status", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_monitoring_requires_permission(client, db_session):
    org = (await create_org_admin(db_session))[0]
    bare_user = await create_user(db_session, org.id)

    resp = await client.get("/monitoring/usage", headers=auth_headers(bare_user))

    assert resp.status_code == 403
