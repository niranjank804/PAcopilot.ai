"""Visual RAG end to end: PDF in, page images to the model.

Two things here are deliberately not mocked. Rasterization runs for
real, on genuinely valid PDFs, because a fake `b"%PDF-fake"` renders
nothing and would let every test pass without exercising the pipeline.
And image storage runs through the real `StorageBackend`, so the
tenant-prefix check the S3 backend performs is the same code path in
tests as in production.

The embedding provider *is* faked, but with one that discriminates
between pages rather than returning a constant — a fake that gives
every page the same vector makes "search returns the right page"
unassertable, which is the only claim worth testing.
"""

import uuid

import pytest

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatResponse, StreamEvent, Usage
from src.core.config import settings
from src.database.models.visual_page import VisualPage
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.embeddings.registry import EMBEDDING_PROVIDERS
from src.knowledge.service import knowledge_service
from src.knowledge.visual.service import visual_service
from sqlalchemy import select
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.fixtures.pdfs import build_pdf

# Pages are built around these words, and the fake embedder maps each to
# its own axis. So "what happened in EMEA?" is genuinely closer to the
# EMEA page than to the APAC one, and a retrieval assertion means
# something.
TOPICS = ["emea", "apac", "latam"]


class KeywordEmbeddingProvider(EmbeddingProvider):
    """A unit vector on the axis of whichever topic the text mentions.

    Crude, deterministic, and offline — but it makes similarity behave
    the way a real embedder does for this fixture's purposes: same
    topic, close; different topic, orthogonal.
    """

    async def embed(self, texts):
        vectors = []

        for text in texts:
            lowered = text.lower()
            vector = [1.0 if topic in lowered else 0.0 for topic in TOPICS]

            if not any(vector):
                # Off every axis, so it matches no topic query rather
                # than tying with all of them.
                vector = [0.0, 0.0, 0.0]
                vector.append(1.0)
            else:
                vector.append(0.0)

            vectors.append(vector)

        return vectors


class RecordingChatProvider(AIProvider):
    """Captures the request so the attachments can be inspected."""

    def __init__(self):
        self.last_request = None

    async def chat(self, request):
        self.last_request = request

        return ChatResponse(
            content="The EMEA variance was driven by FX.",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=5, output_tokens=2),
        )

    async def stream_chat(self, request):
        yield StreamEvent(type="text_delta", text="x")

    async def count_tokens(self, request):
        return 1


@pytest.fixture
def keyword_embeddings():
    original = EMBEDDING_PROVIDERS.get("openai")
    EMBEDDING_PROVIDERS["openai"] = KeywordEmbeddingProvider()
    yield
    if original is not None:
        EMBEDDING_PROVIDERS["openai"] = original


@pytest.fixture
def recording_chat():
    original = PROVIDERS.get("anthropic")
    provider = RecordingChatProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture(autouse=True)
def visual_rag_on(monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_RAG_ENABLED", True)
    monkeypatch.setattr(settings, "VISUAL_RAG_PROVIDER", "text-proxy")
    # The fake embedder is 4-dimensional and orthogonal, so a matching
    # page scores 1.0 and a non-matching one 0.0. Any floor in between
    # works; this keeps the intent visible.
    monkeypatch.setattr(settings, "VISUAL_RAG_MINIMUM_SCORE", 0.5)


# Each comfortably over MINIMUM_TEXT_CHARACTERS. Shorter strings are
# stored without an embedding — correctly, since a near-empty page
# cannot be placed meaningfully in a vector space — which would make
# these retrieval assertions fail for a reason unrelated to retrieval.
# `test_a_page_with_no_text_is_stored_but_not_embedded` covers that path
# deliberately.
REPORT_PAGES = [
    "EMEA quarterly variance driven by currency movement and pricing",
    "APAC revenue bridge with volume effects and mix commentary detail",
    "LATAM cost base commentary covering headcount and inflation impact",
]


async def _upload(db, org, admin, *, pages=None, filename="variance-pack.pdf"):
    return await knowledge_service.upload_document(
        db,
        organization_id=org.id,
        user_id=admin.id,
        filename=filename,
        content_type="application/pdf",
        file_bytes=build_pdf(pages or REPORT_PAGES),
    )


class TestIndexing:

    @pytest.mark.asyncio
    async def test_uploading_a_pdf_indexes_every_page(
        self, db_session, keyword_embeddings
    ):
        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        pages = sorted(rows.scalars().all(), key=lambda page: page.page_number)

        assert [page.page_number for page in pages] == [1, 2, 3]
        assert document.processing_status == "completed"

    @pytest.mark.asyncio
    async def test_each_page_image_is_retrievable(
        self, db_session, keyword_embeddings
    ):
        """The reference is not merely stored, it resolves to a JPEG."""

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        page = rows.scalars().first()

        image = await visual_service.load_image(
            db_session, organization_id=org.id, page=page
        )

        assert image.startswith(b"\xff\xd8\xff")

    @pytest.mark.asyncio
    async def test_the_text_index_still_happens(
        self, db_session, keyword_embeddings
    ):
        """Visual indexing is additive, not a replacement."""

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        matches = await knowledge_service.search(
            db_session, organization_id=org.id, query="EMEA"
        )

        assert matches
        assert document.id in {match.chunk.document_id for match in matches}

    @pytest.mark.asyncio
    async def test_reindexing_replaces_rather_than_duplicates(
        self, db_session, keyword_embeddings
    ):
        """The bug the unique constraint exists to prevent.

        The reference implementation keys rows on Python's `hash()`,
        which is salted per process, so re-ingesting a document writes a
        second full set of pages that then competes with the first for
        retrieval slots.
        """

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        await visual_service.index_document(
            db_session,
            document=document,
            organization_id=org.id,
            file_bytes=build_pdf(REPORT_PAGES),
        )

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )

        assert len(rows.scalars().all()) == 3

    @pytest.mark.asyncio
    async def test_a_page_with_no_text_is_stored_but_not_embedded(
        self, db_session, keyword_embeddings
    ):
        """A scan or a full-page figure, under the text-proxy provider.

        The image is worth keeping — ColPali could index it later — but
        embedding its handful of characters would place it arbitrarily
        in the vector space and let it surface for unrelated queries.
        """

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin, pages=["x"])

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        [page] = rows.scalars().all()

        assert page.image_reference
        assert page.embedding is None


class TestSearch:

    @pytest.mark.asyncio
    async def test_the_relevant_page_is_returned(
        self, db_session, keyword_embeddings
    ):
        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        matches = await visual_service.search(
            db_session, organization_id=org.id, query="APAC revenue"
        )

        assert matches
        assert matches[0].page.page_number == 2

    @pytest.mark.asyncio
    async def test_an_unanswerable_question_returns_nothing(
        self, db_session, keyword_embeddings
    ):
        """The floor that stops confident-looking irrelevant evidence.

        Same reasoning as retrieval.MINIMUM_SCORE for text: without it,
        every question returns the top pages whatever they contain, and
        the model is handed pictures that cannot answer it.
        """

        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        matches = await visual_service.search(
            db_session,
            organization_id=org.id,
            query="unrelated question about warehouse logistics",
        )

        assert matches == []

    @pytest.mark.asyncio
    async def test_results_are_capped(self, db_session, keyword_embeddings):
        org, admin = await create_org_admin(db_session)

        await _upload(
            db_session,
            org,
            admin,
            pages=[
                "EMEA commentary page one with sufficient descriptive text",
                "EMEA commentary page two with sufficient descriptive text",
                "EMEA commentary page three with sufficient descriptive text",
            ],
        )

        matches = await visual_service.search(
            db_session, organization_id=org.id, query="EMEA", top_k=2
        )

        assert len(matches) == 2

    @pytest.mark.asyncio
    async def test_one_organization_cannot_see_anothers_pages(
        self, db_session, keyword_embeddings
    ):
        """Tenancy, at the retrieval boundary."""

        org_a, admin_a = await create_org_admin(db_session)
        org_b, _ = await create_org_admin(db_session)

        await _upload(db_session, org_a, admin_a)

        matches = await visual_service.search(
            db_session, organization_id=org_b.id, query="EMEA"
        )

        assert matches == []

    @pytest.mark.asyncio
    async def test_pages_from_another_provider_are_not_ranked(
        self, db_session, keyword_embeddings
    ):
        """Vectors from different providers are not comparable.

        Ranking a ColPali page against a text-proxy page compares
        numbers with no relationship, and whichever happens to score
        higher wins for no reason.
        """

        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        await db_session.execute(
            VisualPage.__table__.update().values(embedding_model="colpali")
        )

        matches = await visual_service.search(
            db_session, organization_id=org.id, query="EMEA"
        )

        assert matches == []


class TestAnswering:

    @pytest.mark.asyncio
    async def test_page_images_are_sent_to_the_model(
        self, db_session, keyword_embeddings, recording_chat
    ):
        """The whole point of the feature.

        What reaches the model is the rendered page, not pypdf's
        serialisation of it — which is what lets a chart or a pivot
        table be read as what it is.
        """

        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="What drove the EMEA variance?",
        )

        [user_message] = [
            message
            for message in recording_chat.last_request.messages
            if message.role == "user"
        ]

        assert user_message.attachments
        assert all(
            attachment.media_type == "image/jpeg"
            for attachment in user_message.attachments
        )

    @pytest.mark.asyncio
    async def test_the_model_is_told_which_page_each_image_is(
        self, db_session, keyword_embeddings, recording_chat
    ):
        """Otherwise a citation cannot be checked by the reader."""

        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="What drove the EMEA variance?",
        )

        context = recording_chat.last_request.system_context or ""

        assert "variance-pack.pdf" in context
        assert "page 1" in context

    @pytest.mark.asyncio
    async def test_page_citations_are_returned(
        self, db_session, keyword_embeddings, recording_chat
    ):
        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        result = await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="What drove the EMEA variance?",
        )

        assert result.page_citations
        assert result.page_citations[0].filename == "variance-pack.pdf"
        assert result.page_citations[0].page_number == 1

    @pytest.mark.asyncio
    async def test_an_unanswerable_question_attaches_no_images(
        self, db_session, keyword_embeddings, recording_chat
    ):
        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="unrelated question about warehouse logistics",
        )

        [user_message] = [
            message
            for message in recording_chat.last_request.messages
            if message.role == "user"
        ]

        assert not user_message.attachments


class TestDegradation:

    @pytest.mark.asyncio
    async def test_a_visual_failure_does_not_fail_the_upload(
        self, db_session, keyword_embeddings, monkeypatch
    ):
        """Text search is what the product has always relied on.

        No GPU, an image-only PDF, an unreachable object store — none of
        those should make a document unsearchable by text.
        """

        async def explode(*args, **kwargs):
            raise RuntimeError("no GPU available")

        monkeypatch.setattr(visual_service, "index_document", explode)

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        assert document.processing_status == "completed"
        assert "no GPU available" in (document.visual_index_error or "")

    @pytest.mark.asyncio
    async def test_a_visual_search_failure_still_answers_from_text(
        self, db_session, keyword_embeddings, recording_chat, monkeypatch
    ):
        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        async def explode(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(visual_service, "search", explode)

        result = await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="What drove the EMEA variance?",
        )

        assert result.chat_result.content
        assert result.page_citations == []

    @pytest.mark.asyncio
    async def test_a_missing_page_image_is_skipped_not_fatal(
        self, db_session, keyword_embeddings, recording_chat
    ):
        """A row and its object can diverge — a restored database, an
        expired lifecycle rule. The other pages are still evidence.
        """

        org, admin = await create_org_admin(db_session)

        await _upload(db_session, org, admin)

        await db_session.execute(
            VisualPage.__table__.update().values(
                image_reference=f"db://{uuid.uuid4()}"
            )
        )

        result = await knowledge_service.ask(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            query="What drove the EMEA variance?",
        )

        assert result.chat_result.content

    @pytest.mark.asyncio
    async def test_disabling_the_feature_skips_indexing(
        self, db_session, keyword_embeddings, monkeypatch
    ):
        monkeypatch.setattr(settings, "VISUAL_RAG_ENABLED", False)

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )

        assert rows.scalars().all() == []
        assert document.processing_status == "completed"


class TestDeletion:

    @pytest.mark.asyncio
    async def test_deleting_a_document_removes_its_pages(
        self, db_session, keyword_embeddings
    ):
        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        await knowledge_service.delete_document(db_session, document.id, org.id)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )

        assert rows.scalars().all() == []

    @pytest.mark.asyncio
    async def test_the_stored_images_go_too(
        self, db_session, keyword_embeddings
    ):
        """Rows are handled by CASCADE; stored objects are not, and an
        orphaned object is billed indefinitely.
        """

        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        page = rows.scalars().first()
        reference = page.image_reference

        await knowledge_service.delete_document(db_session, document.id, org.id)

        from src.core.exceptions import NotFoundException
        from src.reports.storage import get_storage_backend

        with pytest.raises(NotFoundException):
            await get_storage_backend().get(
                db_session, organization_id=org.id, reference=reference
            )


class TestApi:

    @pytest.mark.asyncio
    async def test_status_reports_the_active_provider(
        self, client, db_session, keyword_embeddings
    ):
        """Visual indexing degrades silently by design.

        Without this endpoint an administrator cannot tell "no relevant
        pages" apart from "this never worked here".
        """

        _, admin = await create_org_admin(db_session)

        response = await client.get(
            "/knowledge/visual/status", headers=auth_headers(admin)
        )

        assert response.status_code == 200

        data = response.json()["data"]

        assert data["provider"] == "text-proxy"
        assert data["enabled"] is True
        assert data["reason"]

    @pytest.mark.asyncio
    async def test_a_page_image_can_be_fetched(
        self, client, db_session, keyword_embeddings
    ):
        org, admin = await create_org_admin(db_session)

        document = await _upload(db_session, org, admin)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        page = rows.scalars().first()

        response = await client.get(
            f"/knowledge/pages/{page.id}/image", headers=auth_headers(admin)
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content.startswith(b"\xff\xd8\xff")

    @pytest.mark.asyncio
    async def test_another_organizations_page_is_not_served(
        self, client, db_session, keyword_embeddings
    ):
        """A citation id is exactly the kind of value that ends up in a
        URL, so this is the check that matters most on this endpoint.
        """

        org_a, admin_a = await create_org_admin(db_session)
        _, admin_b = await create_org_admin(db_session)

        document = await _upload(db_session, org_a, admin_a)

        rows = await db_session.execute(
            select(VisualPage).where(VisualPage.document_id == document.id)
        )
        page = rows.scalars().first()

        response = await client.get(
            f"/knowledge/pages/{page.id}/image", headers=auth_headers(admin_b)
        )

        # 404, not 403 — whether a page id exists is itself information
        # about another organization's documents.
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_an_unknown_page_is_404(self, client, db_session):
        _, admin = await create_org_admin(db_session)

        response = await client.get(
            f"/knowledge/pages/{uuid.uuid4()}/image", headers=auth_headers(admin)
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_page_images_require_authentication(self, client, db_session):
        response = await client.get(f"/knowledge/pages/{uuid.uuid4()}/image")

        assert response.status_code in (401, 403)
