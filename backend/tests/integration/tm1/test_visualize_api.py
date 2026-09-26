from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import src.tm1.crypto as crypto_module
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatResponse, StreamEvent, ToolCall, Usage
from src.core.config import settings
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
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
    # What TM1py's execute_mdx returns: one key per cell, a tuple of member
    # unique names, and the requested properties.
    client.cubes.cells.execute_mdx.return_value = {
        ("[Period].[Period].[Jan-2026]", "[Version].[Version].[Actual]"): {"Value": 125000.0},
        ("[Period].[Period].[Feb-2026]", "[Version].[Version].[Actual]"): {"Value": 131000.0},
        ("[Period].[Period].[Jan-2026]", "[Version].[Version].[Budget]"): {"Value": 120000.0},
        ("[Period].[Period].[Feb-2026]", "[Version].[Version].[Budget]"): {"Value": "n/a"},
    }
    # The analyst's own execute_mdx tool reads the flat form.
    client.cubes.cells.execute_mdx_elements_value_dict.return_value = {
        "Jan-2026|Actual": 125000.0,
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
    assert {"label": "Jan-2026|Actual", "value": 125000.0} in body["cells"]

    # Each dimension kept apart, so the page can pivot the result.
    table = body["table"]
    assert table["dimensions"] == ["Period", "Version"]
    assert {"members": {"Period": "Feb-2026", "Version": "Actual"}, "value": 131000.0} in table["rows"]
    # A text cell is a value, not a crash.
    assert {"members": {"Period": "Feb-2026", "Version": "Budget"}, "value": "n/a"} in table["rows"]


@pytest.mark.asyncio
async def test_visualize_runs_stay_out_of_chat_history(
    client, db_session, tm1_credentials_key, fake_tm1_client, fake_analyst_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = (await _create_connection(client, headers)).json()["data"]["id"]

    chat_resp = await client.post("/ai/chat", json={"message": "Why did zLoad fail?"}, headers=headers)
    assert chat_resp.status_code == 200
    viz_resp = await client.post(
        f"/tm1/connections/{connection_id}/visualize",
        json={"query": "show me revenue by month"},
        headers=headers,
    )
    assert viz_resp.status_code == 200

    listed = (await client.get("/ai/conversations", headers=headers)).json()["data"]
    assert [c["id"] for c in listed] == [chat_resp.json()["data"]["conversation_id"]]

    # Still recorded, so what it cost still counts against the quota.
    conversations = (
        await db_session.execute(select(AIConversation).where(AIConversation.user_id == admin.id))
    ).scalars().all()
    visualize = [c for c in conversations if c.purpose == "visualize"]
    assert len(visualize) == 1
    usage = (
        await db_session.execute(select(AIUsage).where(AIUsage.conversation_id == visualize[0].id))
    ).scalars().all()
    assert usage


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


def _provider_answering(content: str):
    class Provider(AIProvider):
        async def chat(self, request):
            return ChatResponse(
                content=content,
                model=request.model,
                stop_reason="end_turn",
                usage=Usage(input_tokens=5, output_tokens=2),
            )

        async def stream_chat(self, request):
            yield StreamEvent(type="text_delta", text="x")

        async def count_tokens(self, request):
            return 1

    return Provider()


@pytest.mark.asyncio
async def test_visualize_accepts_a_block_fenced_without_json(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    """Models fence JSON as ``` as often as ```json; both used to be
    required to be the latter, and the other failed the request."""

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = (await _create_connection(client, headers)).json()["data"]["id"]

    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = _provider_answering(
        'Revenue is up.\n```\n{"cube_name": "Sales", "mdx": "SELECT X FROM [Sales]"}\n```'
    )
    try:
        resp = await client.post(
            f"/tm1/connections/{connection_id}/visualize",
            json={"query": "revenue"},
            headers=headers,
        )
    finally:
        if original is not None:
            PROVIDERS["anthropic"] = original

    assert resp.status_code == 200
    assert resp.json()["data"]["mdx"] == "SELECT X FROM [Sales]"


class ToolThenNoJsonProvider(AIProvider):
    """Runs each query with execute_mdx, one per round, then answers
    without the JSON block."""

    def __init__(self, connection_id: str, queries=("SELECT PROVEN FROM [Sales]",)):
        self.connection_id = connection_id
        self.queries = list(queries)
        self.rounds = 0

    async def chat(self, request):
        self.rounds += 1

        if self.rounds <= len(self.queries):
            return ChatResponse(
                content="",
                model=request.model,
                stop_reason="tool_use",
                tool_calls=[
                    ToolCall(
                        id=f"call-{self.rounds}",
                        name="execute_mdx",
                        input={
                            "connection_id": self.connection_id,
                            "mdx": self.queries[self.rounds - 1],
                        },
                    )
                ],
                usage=Usage(input_tokens=5, output_tokens=2),
            )

        return ChatResponse(
            content="Revenue by month is shown.",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=5, output_tokens=2),
        )

    async def stream_chat(self, request):
        yield StreamEvent(type="text_delta", text="x")

    async def count_tokens(self, request):
        return 1


@pytest.mark.asyncio
async def test_visualize_uses_the_query_the_agent_proved_when_it_forgets_the_block(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = (await _create_connection(client, headers)).json()["data"]["id"]

    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = ToolThenNoJsonProvider(connection_id)
    try:
        resp = await client.post(
            f"/tm1/connections/{connection_id}/visualize",
            json={"query": "revenue by month"},
            headers=headers,
        )
    finally:
        if original is not None:
            PROVIDERS["anthropic"] = original

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["mdx"] == "SELECT PROVEN FROM [Sales]"
    assert body["cube_name"] == "Sales"


@pytest.mark.asyncio
async def test_visualize_skips_a_last_query_that_returned_nothing(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    # The agent found data (Plan), then explored a query that came back
    # empty (Actual for a future year), and gave up without a block. The
    # page must show the data it found, not the empty last attempt.
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = (await _create_connection(client, headers)).json()["data"]["id"]

    with_data = fake_tm1_client.cubes.cells.execute_mdx.return_value
    fake_tm1_client.cubes.cells.execute_mdx.side_effect = lambda mdx, **_: (
        with_data if "PLAN" in mdx else {}
    )

    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = ToolThenNoJsonProvider(
        connection_id,
        queries=["SELECT PLAN FROM [Income]", "SELECT ACTUAL FROM [Financial Summary]"],
    )
    try:
        resp = await client.post(
            f"/tm1/connections/{connection_id}/visualize",
            json={"query": "revenue by month, actual vs budget"},
            headers=headers,
        )
    finally:
        if original is not None:
            PROVIDERS["anthropic"] = original

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["mdx"] == "SELECT PLAN FROM [Income]"
    assert body["cube_name"] == "Income"
    assert body["table"]["rows"]


@pytest.mark.asyncio
async def test_edited_mdx_reruns_without_the_ai(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = (await _create_connection(client, headers)).json()["data"]["id"]

    resp = await client.post(
        f"/tm1/connections/{connection_id}/visualize/run",
        json={"mdx": "SELECT {[Period].[Jan-2026]} ON 0 FROM [Sales]"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["cube_name"] == "Sales"
    assert body["table"]["dimensions"] == ["Period", "Version"]
    assert len(body["table"]["rows"]) == 4


@pytest.mark.asyncio
async def test_edited_mdx_needs_tm1_read(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection_id = (
        await _create_connection(client, auth_headers(admin))
    ).json()["data"]["id"]
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    resp = await client.post(
        f"/tm1/connections/{connection_id}/visualize/run",
        json={"mdx": "SELECT {} ON 0 FROM [Sales]"},
        headers=auth_headers(viewer),
    )

    assert resp.status_code == 403
