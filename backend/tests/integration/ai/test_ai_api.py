from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from src.database.models.audit_log import AuditLog
from tests.fixtures.factories import auth_headers, create_org_admin, create_organization, create_user


class FakeProvider(AIProvider):

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="fake reply",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="fake reply")
        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 7


@pytest.fixture
def fake_provider():
    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = FakeProvider()
    yield
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_chat_endpoint_returns_envelope(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["content"] == "fake reply"
    assert body["data"]["usage"]["total_tokens"] == 10


@pytest.mark.asyncio
async def test_chat_endpoint_writes_audit_log(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "AIConversation",
            AuditLog.action == "chat",
        )
    )
    logs = [
        log for log in result.scalars().all()
        if str(log.entity_id) == conversation_id
    ]
    assert len(logs) == 1
    assert logs[0].user_id == admin.id


@pytest.mark.asyncio
async def test_chat_stream_endpoint_streams_and_persists(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat/stream",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = [
        line[len("data: "):]
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert len(events) == 2

    import json

    first = json.loads(events[0])
    last = json.loads(events[1])

    assert first["type"] == "text_delta"
    assert first["text"] == "fake reply"
    assert last["type"] == "done"
    assert last["usage"]["input_tokens"] == 7

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "AIConversation",
            AuditLog.action == "chat_stream",
        )
    )
    logs = [
        log for log in result.scalars().all()
        if str(log.entity_id) == last["conversation_id"]
    ]
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_chat_endpoint_requires_permission(client, db_session, fake_provider):
    org = await create_organization(db_session)
    bare_user = await create_user(db_session, org.id)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(bare_user),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_chat_endpoint_with_image_attachment_persists_filename_marker(
    client, db_session, fake_provider
):
    import base64

    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={
            "message": "What's in this?",
            "attachments": [
                {
                    "filename": "screenshot.png",
                    "content_type": "image/png",
                    "data": base64.b64encode(b"fake-png-bytes").decode(),
                }
            ],
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "fake reply"

    messages_resp = await client.get(
        f"/ai/conversations/{body['conversation_id']}/messages",
        headers=auth_headers(admin),
    )
    stored_user_message = messages_resp.json()["data"][0]["content"]
    assert "screenshot.png" in stored_user_message
    assert "What's in this?" in stored_user_message


@pytest.mark.asyncio
async def test_chat_endpoint_rejects_unsupported_attachment_type(
    client, db_session, fake_provider
):
    import base64

    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={
            "message": "run this",
            "attachments": [
                {
                    "filename": "malware.exe",
                    "content_type": "application/octet-stream",
                    "data": base64.b64encode(b"x").decode(),
                }
            ],
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
