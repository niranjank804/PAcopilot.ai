"""Promotion DEV -> QA -> PROD and the deployment package (phase 7)."""

import pytest

from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _draft, _execute


async def _applied_on_dev(client, headers):
    dev = await _connection(client, headers, "dev")
    change = await _draft(client, headers, dev)
    applied = await _execute(client, headers, dev, change)
    assert applied.status_code == 200, applied.text
    return dev, change


async def _promote(client, headers, connection_id, change_id, target):
    return await client.post(
        f"/tm1/connections/{connection_id}/changes/{change_id}/promote",
        json={"target_connection_id": target},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_a_change_travels_dev_to_qa_to_prod_with_its_package(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    headers = auth_headers(admin)
    approver = await create_user(db_session, org_id)
    await grant_system_role(db_session, approver.id, "Organization Admin")
    approver_headers = auth_headers(approver)

    dev, dev_change = await _applied_on_dev(client, headers)
    qa = await _connection(client, headers, "qa")
    prod = await _connection(client, headers, "prod")

    to_qa = await _promote(client, headers, dev, dev_change, qa)
    assert to_qa.status_code == 201, to_qa.text
    qa_change = to_qa.json()["data"]
    assert qa_change["status"] == "draft" and qa_change["promoted_from"] == dev_change
    assert (await _execute(client, headers, qa, qa_change["id"])).status_code == 200

    to_prod = await _promote(client, headers, qa, qa_change["id"], prod)
    assert to_prod.status_code == 201, to_prod.text
    prod_change = to_prod.json()["data"]["id"]

    package = (await client.get(
        f"/tm1/connections/{prod}/changes/{prod_change}/package", headers=headers
    )).json()["data"]

    assert [s["environment"] for s in package["stages"]] == ["DEV", "QA", "PROD"]
    assert package["evidence"]["verified_in"] == ["DEV", "QA"]
    assert package["evidence"]["content_unchanged_since_first_stage"] is True
    assert "someone other than the requester" in package["approval_rule"]
    assert "Roll back restores" in package["rollback_plan"]
    assert package["diff"]["proposed"] == {"rules": "['A'] = N: 2;"}

    # Still two people on PROD, promoted or not.
    assert (await _execute(client, headers, prod, prod_change)).status_code == 403
    assert (await _execute(client, approver_headers, prod, prod_change)).status_code == 200


@pytest.mark.asyncio
async def test_dev_cannot_skip_qa(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev, change = await _applied_on_dev(client, headers)
    prod = await _connection(client, headers, "prod")

    refused = await _promote(client, headers, dev, change, prod)

    assert refused.status_code == 422, refused.text
    assert "promoted to QA next" in refused.text


@pytest.mark.asyncio
async def test_only_an_applied_change_is_promoted(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    qa = await _connection(client, headers, "qa")
    draft = await _draft(client, headers, dev)

    refused = await _promote(client, headers, dev, draft, qa)

    assert refused.status_code == 422
    assert "applied and verified" in refused.text


@pytest.mark.asyncio
async def test_a_rolled_back_change_is_not_promoted(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev, change = await _applied_on_dev(client, headers)
    qa = await _connection(client, headers, "qa")
    rolled = await client.post(f"/tm1/connections/{dev}/changes/{change}/rollback", headers=headers)
    assert rolled.status_code == 200, rolled.text

    refused = await _promote(client, headers, dev, change, qa)

    assert refused.status_code == 422
