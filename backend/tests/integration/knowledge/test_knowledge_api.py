import pytest

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatResponse, StreamEvent, Usage
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.embeddings.registry import EMBEDDING_PROVIDERS
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
    grant_system_role,
)


class FakeEmbeddingProvider(EmbeddingProvider):

    async def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeChatProvider(AIProvider):

    async def chat(self, request):
        return ChatResponse(
            content="grounded answer",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=5, output_tokens=2),
        )

    async def stream_chat(self, request):
        yield StreamEvent(type="text_delta", text="x")

    async def count_tokens(self, request):
        return 1


@pytest.fixture
def fake_embeddings():
    original = EMBEDDING_PROVIDERS.get("openai")
    EMBEDDING_PROVIDERS["openai"] = FakeEmbeddingProvider()
    yield
    if original is not None:
        EMBEDDING_PROVIDERS["openai"] = original


@pytest.fixture
def fake_chat_provider():
    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = FakeChatProvider()
    yield
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_upload_list_get_document(client, db_session, fake_embeddings):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    upload_resp = await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"Hello knowledge base", "text/plain")},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    body = upload_resp.json()
    assert body["success"] is True
    assert body["data"]["processing_status"] == "completed"
    document_id = body["data"]["id"]

    list_resp = await client.get("/knowledge/documents", headers=headers)
    assert list_resp.status_code == 200
    assert any(d["id"] == document_id for d in list_resp.json()["data"])

    get_resp = await client.get(
        f"/knowledge/documents/{document_id}", headers=headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_document_upload_requires_write_permission(
    client, db_session, fake_embeddings
):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    resp = await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"content", "text/plain")},
        headers=auth_headers(viewer),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_org_document_access_is_404(client, db_session, fake_embeddings):
    org_a, admin_a = await create_org_admin(db_session)
    org_b, admin_b = await create_org_admin(db_session)
    headers_a = auth_headers(admin_a)
    headers_b = auth_headers(admin_b)

    upload_resp = await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"Org A's notes", "text/plain")},
        headers=headers_a,
    )
    document_id = upload_resp.json()["data"]["id"]

    get_resp = await client.get(
        f"/knowledge/documents/{document_id}",
        headers=headers_b,
    )
    assert get_resp.status_code == 404

    delete_resp = await client.delete(
        f"/knowledge/documents/{document_id}",
        headers=headers_b,
    )
    assert delete_resp.status_code == 404


@pytest.mark.asyncio
async def test_search_endpoint_returns_matches(client, db_session, fake_embeddings):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"Hello knowledge base", "text/plain")},
        headers=headers,
    )

    resp = await client.post(
        "/knowledge/search",
        json={"query": "hello", "top_k": 5},
        headers=headers,
    )

    assert resp.status_code == 200
    results = resp.json()["data"]
    assert len(results) == 1
    assert results[0]["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_search_returns_clean_error_when_embedding_provider_fails(
    client, db_session, monkeypatch,
):
    from src.knowledge.embeddings.registry import EMBEDDING_PROVIDERS

    class BrokenEmbeddingProvider(EmbeddingProvider):
        async def embed(self, texts):
            raise RuntimeError("Missing credentials.")

    original = EMBEDDING_PROVIDERS.get("openai")
    EMBEDDING_PROVIDERS["openai"] = BrokenEmbeddingProvider()

    try:
        org, admin = await create_org_admin(db_session)

        resp = await client.post(
            "/knowledge/search",
            json={"query": "hello", "top_k": 5},
            headers=auth_headers(admin),
        )

        assert resp.status_code == 500
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "KNOWLEDGE_SERVICE_ERROR"
        assert "unavailable" in body["error"]["message"]
    finally:
        if original is not None:
            EMBEDDING_PROVIDERS["openai"] = original


@pytest.mark.asyncio
async def test_ask_endpoint_returns_answer_with_citations(
    client, db_session, fake_embeddings, fake_chat_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"Hello knowledge base", "text/plain")},
        headers=headers,
    )

    resp = await client.post(
        "/knowledge/ask",
        json={"query": "what's in the notes?"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "grounded answer"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_ask_endpoint_with_agent_grounds_in_knowledge_and_enables_tools(
    client, db_session, fake_embeddings, fake_chat_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"Hello knowledge base", "text/plain")},
        headers=headers,
    )

    resp = await client.post(
        "/knowledge/ask",
        json={"query": "what's in the notes?", "agent": "developer"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "grounded answer"
    # Knowledge grounding still happens even with an agent selected.
    assert len(body["citations"]) == 1


@pytest.mark.asyncio
async def test_ask_endpoint_rejects_unknown_agent(
    client, db_session, fake_embeddings, fake_chat_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.post(
        "/knowledge/ask",
        json={"query": "hello", "agent": "not-a-real-agent"},
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_explain_error_classifies_and_grounds_via_troubleshooter_agent(
    client, db_session, fake_embeddings, fake_chat_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.post(
        "/knowledge/explain-error",
        json={"error_text": "Could not logon: invalid credentials"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["error_type"] == "authentication"
    assert body["severity"] == "high"
    assert body["content"] == "grounded answer"


@pytest.mark.asyncio
async def test_explain_error_requires_knowledge_read_permission(
    client, db_session, fake_embeddings, fake_chat_provider
):
    org = await create_organization(db_session)
    # No role granted at all — knowledge.read is otherwise universal across
    # every seeded system role, so this is the only way to reach a 403 here.
    unassigned_user = await create_user(db_session, org.id)

    resp = await client.post(
        "/knowledge/explain-error",
        json={"error_text": "Some error"},
        headers=auth_headers(unassigned_user),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_document(client, db_session, fake_embeddings):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    upload_resp = await client.post(
        "/knowledge/documents",
        files={"file": ("notes.txt", b"content", "text/plain")},
        headers=headers,
    )
    document_id = upload_resp.json()["data"]["id"]

    delete_resp = await client.delete(
        f"/knowledge/documents/{document_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    get_resp = await client.get(
        f"/knowledge/documents/{document_id}", headers=headers
    )
    assert get_resp.status_code == 404
