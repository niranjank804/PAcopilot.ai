"""TM1_MODE: what this deployment lets the assistant do to TM1.

governed (default): the assistant drafts, a person executes — apply_change
is not offered and refuses. readwrite: on DEV only, at the user's request,
the assistant executes its own validated draft with the same checks,
snapshot, audit and rollback. readonly: nobody applies, rolls back or
promotes anything here.
"""

import json
import uuid

import pytest
from sqlalchemy import select

from src.ai import orchestrator as orchestrator_module
from src.ai.tools.registry import list_tools
from src.ai.tools.tm1.changes import ApplyChangeTool
from src.core.config import settings
from src.database.models.audit_log import AuditLog
from src.database.models.tm1_change import TM1Change
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _draft, _user_with


@pytest.fixture
def mode(monkeypatch):
    def set_mode(value: str):
        monkeypatch.setattr(settings, "TM1_MODE", value)

    return set_mode


async def _apply(db_session, user, connection_id, change_id, **extra):
    # Ids are read before the session is used again: a commit elsewhere
    # expires the user row, and reading it then needs a database round trip.
    org_id, user_id = user.organization_id, user.id
    db_session.info.pop("organization_id", None)
    return json.loads(await ApplyChangeTool().execute(
        db_session, organization_id=org_id, user_id=user_id,
        connection_id=connection_id, change_id=change_id, **extra,
    ))


async def _status(db_session, change_id):
    db_session.info.pop("organization_id", None)
    return (await db_session.get(TM1Change, uuid.UUID(change_id))).status


def _offered() -> set[str]:
    return {t.name for t in orchestrator_module._tools_for_mode(list_tools())}


@pytest.mark.asyncio
async def test_governed_is_the_default_and_the_assistant_cannot_apply(client, db_session, tm1_credentials_key,
                                                                       fake_tm1_client):
    assert settings.TM1_MODE == "governed"
    assert "apply_change" not in _offered()
    assert orchestrator_module.MODE_CONTEXT.get(settings.TM1_MODE) is None

    _org, admin = await create_org_admin(db_session)
    dev = await _connection(client, auth_headers(admin), "dev")
    change = await _draft(client, auth_headers(admin), dev)

    result = await _apply(db_session, admin, dev, change)
    assert result["applied"] is False and "TM1_MODE is governed" in result["error"]
    assert await _status(db_session, change) == "draft"


@pytest.mark.asyncio
async def test_readwrite_applies_the_users_own_draft_on_dev_with_audit(client, db_session, tm1_credentials_key,
                                                                        fake_tm1_client, mode):
    mode("readwrite")
    assert "apply_change" in _offered()
    assert "DEV" in orchestrator_module.MODE_CONTEXT["readwrite"]

    _org, admin = await create_org_admin(db_session)
    dev = await _connection(client, auth_headers(admin), "dev")
    change = await _draft(client, auth_headers(admin), dev)

    result = await _apply(db_session, admin, dev, change)
    assert result["applied"] is True and result["status"] == "executed", result
    assert result["environment"] == "dev"
    assert await _status(db_session, change) == "executed"

    db_session.info.pop("organization_id", None)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "execute_change", AuditLog.entity_id == uuid.UUID(dev))
    )).scalars().all()
    assert any(r.new_values.get("applied_by") == "assistant" and r.new_values.get("change_id") == change
               for r in rows)

    again = await _apply(db_session, admin, dev, change)
    assert again["applied"] is False and "already executed" in again["error"]


@pytest.mark.asyncio
async def test_readwrite_never_applies_on_qa_or_prod(client, db_session, tm1_credentials_key, fake_tm1_client,
                                                     mode):
    mode("readwrite")
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    for environment in ("qa", "prod"):
        connection = await _connection(client, headers, environment)
        # A person's draft (the assistant cannot even draft on PROD).
        change = await _draft(client, headers, connection)
        result = await _apply(db_session, admin, connection, change)
        assert result["applied"] is False and environment.upper() in result["error"], result
        assert await _status(db_session, change) == "draft"


@pytest.mark.asyncio
async def test_readwrite_still_needs_the_deploy_right_and_a_clean_draft(client, db_session, tm1_credentials_key,
                                                                          fake_tm1_client, mode):
    mode("readwrite")
    org, admin = await create_org_admin(db_session)
    dev = await _connection(client, auth_headers(admin), "dev")
    member = await _user_with(db_session, org.id, "ai.chat")  # tm1.write but no tm1.deploy
    await db_session.commit()
    change = await _draft(client, auth_headers(member), dev)

    from src.core.exceptions import PermissionDeniedException

    with pytest.raises(PermissionDeniedException):
        await _apply(db_session, member, dev, change)
    assert await _status(db_session, change) == "draft"

    # Someone else's draft is not "yours".
    result = await _apply(db_session, admin, dev, change)
    assert result["applied"] is False and "No such draft of yours" in result["error"]

    # A draft with validation errors is refused before TM1 is touched.
    fake_tm1_client.processes.compile_process.return_value = [{"LineNumber": 1, "Message": "Syntax error"}]
    resp = await client.post(
        f"/tm1/connections/{dev}/changes",
        json={"change_type": "create_process", "target_name": "zzBroken", "new_content": {"prolog": "bad code"}},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    fake_tm1_client.processes.compile_process.return_value = []
    result = await _apply(db_session, admin, dev, resp.json()["data"]["id"])
    assert result["applied"] is False and "validation errors" in result["error"]
    fake_tm1_client.processes.update_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_readonly_refuses_every_write_for_everyone(client, db_session, tm1_credentials_key, fake_tm1_client,
                                                        mode):
    mode("readonly")
    assert "apply_change" not in _offered()
    assert "never changes TM1" in orchestrator_module.MODE_CONTEXT["readonly"]

    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    org_id, admin_id = admin.organization_id, admin.id
    dev = await _connection(client, headers, "dev")
    change = await _draft(client, headers, dev)  # drafting still works
    await db_session.commit()

    for action in ("execute", "rollback"):
        resp = await client.post(f"/tm1/connections/{dev}/changes/{change}/{action}", headers=headers)
        assert resp.status_code == 403, (action, resp.text)
        assert "read-only" in resp.json()["error"]["message"]
    assert await _status(db_session, change) == "draft"

    db_session.info.pop("organization_id", None)
    result = json.loads(await ApplyChangeTool().execute(
        db_session, organization_id=org_id, user_id=admin_id, connection_id=dev, change_id=change,
    ))
    assert result["applied"] is False
