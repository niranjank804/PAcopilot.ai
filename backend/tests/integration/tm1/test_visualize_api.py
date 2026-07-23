from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatResponse, StreamEvent, Usage
from src.core.config import settings
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()
    client.cubes.cells.execute_mdx_elements_value_dict.return_value = {
        "Jan-2026|Actual|Revenue": 125000.0,
        "Feb-2026|Actual|Revenue": 131000.0,
    }

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


class FakeAnalystProvider(AIProvider):
    """Returns a final answer with no tool calls — the orchestrator's tool
    loop ends on the first round since stop_reason isn't "tool_use", so this
    exercises generate_visualization()'s JSON-parsing + re-execution path
    without needing to simulate a multi-round tool-calling conversation."""

    async def chat(self, request):
        return ChatResponse(
            content=(
                "Revenue rose from January to February.\n"
                "```json\n"
                '{"cube_name": "Sales", "mdx": "SELECT ... FROM [Sales]"}\n'
                "```"
            ),
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=5),
        )

    async def stream_chat(self, request):
        yield StreamEvent(type="text_delta", text="x")

    async def count_tokens(self, request):
        return 1


@pytest.fixture
def fake_analyst_provider():
    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = FakeAnalystProvider()
    yield
    if original is not None:
        PROVIDERS["anthropic"] = original


async def _create_connection(client, headers):
    return await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "super-secret",
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_visualize_returns_chart_ready_cells(
    client, db_session, tm1_credentials_key, fake_tm1_client, fake_analyst_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/tm1/connections/{connection_id}/visualize",
        json={"query": "show me revenue by month"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["cube_name"] == "Sales"
    assert body["mdx"] == "SELECT ... FROM [Sales]"
    assert {"label": "Jan-2026|Actual|Revenue", "value": 125000.0} in body["cells"]
    assert {"label": "Feb-2026|Actual|Revenue", "value": 131000.0} in body["cells"]


@pytest.mark.asyncio
async def test_visualize_requires_tm1_read_permission(
    client, db_session, tm1_credentials_key, fake_tm1_client, fake_analyst_provider
):
    org, admin = await create_org_admin(db_session)
    create_resp = await _create_connection(client, auth_headers(admin))
    connection_id = create_resp.json()["data"]["id"]

    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    resp = await client.post(
        f"/tm1/connections/{connection_id}/visualize",
        json={"query": "show me revenue by month"},
        headers=auth_headers(viewer),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_visualize_rejects_response_without_json_block(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    class NoJsonProvider(AIProvider):
        async def chat(self, request):
            return ChatResponse(
                content="I couldn't figure out the right cube.",
                model=request.model,
                stop_reason="end_turn",
                usage=Usage(input_tokens=5, output_tokens=2),
            )

        async def stream_chat(self, request):
            yield StreamEvent(type="text_delta", text="x")

        async def count_tokens(self, request):
            return 1

    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = NoJsonProvider()
    try:
        resp = await client.post(
            f"/tm1/connections/{connection_id}/visualize",
            json={"query": "show me something ambiguous"},
            headers=headers,
        )
    finally:
        if original is not None:
            PROVIDERS["anthropic"] = original

    assert resp.status_code == 422
