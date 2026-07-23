import pytest

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatResponse, StreamEvent, Usage
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.embeddings.registry import EMBEDDING_PROVIDERS
from src.knowledge.service import knowledge_service
from tests.fixtures.factories import create_organization, create_user


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
async def test_upload_document_persists_completed_document(
    db_session, fake_embeddings
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    document = await knowledge_service.upload_document(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        filename="notes.txt",
        content_type="text/plain",
        file_bytes=b"Hello knowledge base",
    )

    assert document.processing_status == "completed"
    assert document.error_message is None


@pytest.mark.asyncio
async def test_upload_document_marks_failed_on_unsupported_type(
    db_session, fake_embeddings
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    document = await knowledge_service.upload_document(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        filename="image.png",
        content_type="image/png",
        file_bytes=b"not text",
    )

    assert document.processing_status == "failed"
    assert document.error_message is not None


@pytest.mark.asyncio
async def test_search_returns_matching_chunks(db_session, fake_embeddings):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await knowledge_service.upload_document(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        filename="notes.txt",
        content_type="text/plain",
        file_bytes=b"Hello knowledge base",
    )

    matches = await knowledge_service.search(
        db_session,
        organization_id=org.id,
        query="hello",
    )

    assert len(matches) == 1
    assert matches[0].chunk.content == "Hello knowledge base"


@pytest.mark.asyncio
async def test_search_is_scoped_to_organization(db_session, fake_embeddings):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    user_a = await create_user(db_session, org_a.id)

    await knowledge_service.upload_document(
        db_session,
        organization_id=org_a.id,
        user_id=user_a.id,
        filename="notes.txt",
        content_type="text/plain",
        file_bytes=b"Org A's private notes",
    )

    matches = await knowledge_service.search(
        db_session,
        organization_id=org_b.id,
        query="notes",
    )

    assert matches == []


@pytest.mark.asyncio
async def test_ask_returns_grounded_answer_with_citations(
    db_session, fake_embeddings, fake_chat_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await knowledge_service.upload_document(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        filename="notes.txt",
        content_type="text/plain",
        file_bytes=b"Hello knowledge base",
    )

    result = await knowledge_service.ask(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        query="what is in the notes?",
    )

    assert result.chat_result.content == "grounded answer"
    assert len(result.citations) == 1
    assert result.citations[0].filename == "notes.txt"
