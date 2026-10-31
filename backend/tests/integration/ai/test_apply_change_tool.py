"""TM1_MODE: what this deployment lets the assistant do to TM1.

governed (default): the assistant drafts, a person executes — apply_change
is not offered and refuses. readwrite: on DEV only, at the user's request,
the assistant executes a draft it proposed itself in the same conversation,
with the same checks, snapshot, audit and rollback. readonly: nobody
applies, rolls back or promotes anything here.
"""

import json
import uuid

import pytest
from sqlalchemy import select

from src.ai import orchestrator as orchestrator_module
from src.ai.tools.registry import list_tools
from src.ai.tools.tm1.changes import ApplyChangeTool, ProposeProcessUpdateTool, ProposeRuleUpdateTool
from src.core.config import settings
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_tool_execution import AIToolExecution
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


def _who(user) -> tuple[uuid.UUID, uuid.UUID]:
    """(organization_id, user_id) — read once, before any commit expires
    the row and reading it needs a database round trip."""

    return user.organization_id, user.id


async def _conversation(db_session, who) -> uuid.UUID:
    org_id, user_id = who
    conversation = AIConversation(organization_id=org_id, user_id=user_id, title="fix the rule")
    db_session.add(conversation)
    await db_session.flush()
    return conversation.id


async def _proposed(db_session, conversation_id, who, connection_id, tool=None, **inputs) -> str:
    """Draft through a propose_* tool and record the call the way the
    orchestrator does — that record is what makes the draft the assistant's
    own, in this conversation."""

    org_id, user_id = who
    tool = tool or ProposeRuleUpdateTool()
    inputs = inputs or {"cube_name": "Sales", "rules": "['A'] = N: 2;"}
    db_session.info.pop("organization_id", None)
    result = await tool.execute(
        db_session, organization_id=org_id, user_id=user_id, connection_id=connection_id, **inputs,
    )
    db_session.add(AIToolExecution(
        conversation_id=conversation_id, organization_id=org_id, user_id=user_id,
        tool_name=tool.name, arguments={"connection_id": connection_id, **inputs},
        status="success", result_summary=result[:500], duration_ms=1,
    ))
    await db_session.flush()
    return json.loads(result)["draft_change_id"]


async def _apply(db_session, who, connection_id, change_id, conversation_id, **extra):
    org_id, user_id = who
    db_session.info.pop("organization_id", None)
    return json.loads(await ApplyChangeTool().execute(
        db_session, organization_id=org_id, user_id=user_id,
        connection_id=connection_id, change_id=change_id, conversation_id=conversation_id, **extra,
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
    who = _who(admin)
    dev = await _connection(client, auth_headers(admin), "dev")
    conversation = await _conversation(db_session, who)
    change = await _proposed(db_session, conversation, who, dev)

    result = await _apply(db_session, who, dev, change, conversation)
    assert result["applied"] is False and "TM1_MODE is governed" in result["error"]
    assert await _status(db_session, change) == "draft"


@pytest.mark.asyncio
async def test_readwrite_applies_the_draft_it_proposed_here_with_audit(client, db_session, tm1_credentials_key,
                                                                        fake_tm1_client, mode):
    mode("readwrite")
    assert "apply_change" in _offered()
    assert "DEV" in orchestrator_module.MODE_CONTEXT["readwrite"]

    _org, admin = await create_org_admin(db_session)
    who = _who(admin)
    dev = await _connection(client, auth_headers(admin), "dev")
    conversation = await _conversation(db_session, who)
    change = await _proposed(db_session, conversation, who, dev)

    result = await _apply(db_session, who, dev, change, conversation)
    assert result["applied"] is True and result["status"] == "executed", result
    assert result["environment"] == "dev"
    assert await _status(db_session, change) == "executed"

    db_session.info.pop("organization_id", None)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "execute_change", AuditLog.entity_id == uuid.UUID(dev))
    )).scalars().all()
    assert any(
        r.new_values.get("applied_by") == "assistant"
        and r.new_values.get("change_id") == change
        and r.new_values.get("conversation_id") == str(conversation)
        and r.new_values.get("impact_acknowledged") is False
        for r in rows
    )

    again = await _apply(db_session, who, dev, change, conversation)
    assert again["applied"] is False and "already executed" in again["error"]


@pytest.mark.asyncio
async def test_readwrite_applies_only_what_it_drafted_in_this_conversation(client, db_session,
                                                                            tm1_credentials_key, fake_tm1_client,
                                                                            mode):
    """A person's console draft, a draft from another conversation, and a
    call with no conversation are all refused; the same tool then applies
    the draft it did propose here, so the refusals were for that reason."""

    mode("readwrite")
    _org, admin = await create_org_admin(db_session)
    who = _who(admin)
    dev = await _connection(client, auth_headers(admin), "dev")
    here = await _conversation(db_session, who)
    elsewhere = await _conversation(db_session, who)

    # Drafts on different cubes stay open side by side (a new draft of the
    # same target supersedes the old one).
    console_draft = await _draft(client, auth_headers(admin), dev)  # Sales, made in the console
    other_draft = await _proposed(db_session, elsewhere, who, dev, cube_name="Costs", rules="['B'] = N: 3;")
    own_draft = await _proposed(db_session, here, who, dev, cube_name="Margin", rules="['C'] = N: 4;")

    for change in (console_draft, other_draft):
        result = await _apply(db_session, who, dev, change, here)
        assert result["applied"] is False and "proposed in this conversation" in result["error"], result
        assert await _status(db_session, change) == "draft"

    result = await _apply(db_session, who, dev, own_draft, None)
    assert result["applied"] is False and "proposed in this conversation" in result["error"]
    assert await _status(db_session, own_draft) == "draft"

    result = await _apply(db_session, who, dev, own_draft, here)
    assert result["applied"] is True, result
    assert await _status(db_session, own_draft) == "executed"


@pytest.mark.asyncio
async def test_readwrite_never_applies_on_qa_or_prod(client, db_session, tm1_credentials_key, fake_tm1_client,
                                                     mode):
    mode("readwrite")
    _org, admin = await create_org_admin(db_session)
    who = _who(admin)
    headers = auth_headers(admin)
    conversation = await _conversation(db_session, who)
    for environment in ("qa", "prod"):
        connection = await _connection(client, headers, environment)
        # A person's draft (the assistant cannot even draft on PROD); the
        # environment is refused before the draft is looked at.
        change = await _draft(client, headers, connection)
        result = await _apply(db_session, who, connection, change, conversation)
        assert result["applied"] is False and environment.upper() in result["error"], result
        assert await _status(db_session, change) == "draft"


@pytest.mark.asyncio
async def test_readwrite_still_needs_the_deploy_right_and_a_clean_draft(client, db_session, tm1_credentials_key,
                                                                          fake_tm1_client, mode):
    mode("readwrite")
    org, admin = await create_org_admin(db_session)
    admin_who = _who(admin)
    dev = await _connection(client, auth_headers(admin), "dev")
    member = await _user_with(db_session, org.id, "ai.chat")  # tm1.write but no tm1.deploy
    member_who = _who(member)
    members_conversation = await _conversation(db_session, member_who)
    change = await _proposed(db_session, members_conversation, member_who, dev)

    from src.core.exceptions import PermissionDeniedException

    with pytest.raises(PermissionDeniedException):
        await _apply(db_session, member_who, dev, change, members_conversation)
    assert await _status(db_session, change) == "draft"

    # Someone else's draft is not "yours", whatever conversation is named.
    result = await _apply(db_session, admin_who, dev, change, members_conversation)
    assert result["applied"] is False and "No such draft of yours" in result["error"]

    # A draft with validation errors is refused before TM1 is touched.
    conversation = await _conversation(db_session, admin_who)
    fake_tm1_client.processes.compile_process.return_value = [{"LineNumber": 1, "Message": "Syntax error"}]
    broken = await _proposed(
        db_session, conversation, admin_who, dev, tool=ProposeProcessUpdateTool(),
        process_name="zzBroken", create_new=True, prolog="bad code",
    )
    fake_tm1_client.processes.compile_process.return_value = []
    result = await _apply(db_session, admin_who, dev, broken, conversation)
    assert result["applied"] is False and "validation errors" in result["error"], result
    fake_tm1_client.processes.update_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_readonly_refuses_every_write_for_everyone(client, db_session, tm1_credentials_key, fake_tm1_client,
                                                        mode):
    mode("readonly")
    assert "apply_change" not in _offered()
    assert "never changes TM1" in orchestrator_module.MODE_CONTEXT["readonly"]

    _org, admin = await create_org_admin(db_session)
    who = _who(admin)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    conversation = await _conversation(db_session, who)
    change = await _proposed(db_session, conversation, who, dev)  # drafting still works
    await db_session.commit()  # the API's own session must see the draft

    for action in ("execute", "rollback"):
        resp = await client.post(f"/tm1/connections/{dev}/changes/{change}/{action}", headers=headers)
        assert resp.status_code == 403, (action, resp.text)
        assert "read-only" in resp.json()["error"]["message"]
    assert await _status(db_session, change) == "draft"

    result = await _apply(db_session, who, dev, change, conversation)
    assert result["applied"] is False
