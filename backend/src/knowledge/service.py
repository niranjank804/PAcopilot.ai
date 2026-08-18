import base64
import hashlib
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.orchestrator import ChatResult, ai_orchestrator
from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.database.models.knowledge_chunk import KnowledgeChunk
from src.database.models.knowledge_document import KnowledgeDocument
from src.knowledge import quality, retrieval
from src.knowledge.chunking import chunk_text
from src.knowledge.embeddings import cache as embedding_cache
from src.knowledge.embeddings.registry import get_embedding_provider
from src.knowledge.exceptions import KnowledgeServiceError
from src.knowledge.loaders.registry import get_loader
from src.knowledge.visual.providers.registry import visual_rag_availability
from src.knowledge.visual.service import visual_service
from src.schemas.ai import AttachmentInput
from src.repositories.knowledge_chunk_repository import knowledge_chunk_repository
from src.repositories.knowledge_document_repository import (
    knowledge_document_repository,
)


class Citation:

    def __init__(
        self,
        document_id: uuid.UUID,
        filename: str,
        chunk_index: int,
        score: float,
    ):
        self.document_id = document_id
        self.filename = filename
        self.chunk_index = chunk_index
        self.score = score


class PageCitation:
    """A citation that points at a page the model actually looked at.

    Separate from `Citation` because the evidence is different in kind:
    a chunk citation says "this text was in the prompt", a page citation
    says "this image was in the prompt". Conflating them would let the
    UI claim a passage was quoted when what was really sent was a
    picture of the page it sits on.
    """

    def __init__(
        self,
        page_id: uuid.UUID,
        document_id: uuid.UUID,
        filename: str,
        page_number: int,
        score: float,
    ):
        self.page_id = page_id
        self.document_id = document_id
        self.filename = filename
        self.page_number = page_number
        self.score = score


class AskResult:

    def __init__(
        self,
        chat_result: ChatResult,
        citations: list[Citation],
        page_citations: list[PageCitation] | None = None,
    ):
        self.chat_result = chat_result
        self.citations = citations
        self.page_citations = page_citations or []


logger = logging.getLogger(__name__)


class KnowledgeService:

    async def get_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> KnowledgeDocument:

        document = await knowledge_document_repository.get_by_id(db, document_id)

        if document is None or document.organization_id != organization_id:
            raise NotFoundException("Document not found.")

        return document

    async def list_documents(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[KnowledgeDocument]:

        return await knowledge_document_repository.list_by_organization(
            db,
            organization_id,
        )

    async def delete_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        document = await self.get_document(db, document_id, organization_id)

        # Before the row: the CASCADE removes visual_pages, but a stored
        # page image outlives its row indefinitely and is billed for the
        # privilege. Deleting the objects needs the references, which
        # only exist while the rows do.
        await visual_service.delete_for_document(
            db,
            organization_id=organization_id,
            document_id=document_id,
        )

        await knowledge_document_repository.delete(db, document)

    async def upload_document(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> KnowledgeDocument:

        checksum = hashlib.sha256(file_bytes).hexdigest()

        # The checksum was computed and stored but never queried, so uploading
        # the same file twice paid to embed it twice and then let both copies
        # compete for the same retrieval slots — the second copy crowding out
        # a different document that had something new to say.
        existing = await knowledge_document_repository.get_by_checksum(
            db, organization_id, checksum
        )

        if existing is not None:
            logger.info(
                "Knowledge document %s matches already-indexed %s; reusing it.",
                filename,
                existing.filename,
            )
            return existing

        document = KnowledgeDocument(
            organization_id=organization_id,
            uploaded_by=user_id,
            filename=filename,
            content_type=content_type,
            checksum=checksum,
            processing_status="pending",
        )
        document = await knowledge_document_repository.create(db, document)

        try:
            loader = get_loader(content_type)
            text = loader.load(file_bytes)

            # Checked before embedding: a junk document costs money to
            # index and then degrades every later search by competing for
            # retrieval slots. Failing here leaves the document row with
            # processing_status='failed' and the reasons in error_message,
            # so the uploader can see exactly what to fix.
            problems = quality.assess(text)

            if problems:
                raise ValueError(
                    "This document was not indexed: " + " ".join(problems)
                )

            chunks = chunk_text(text)

            if not chunks:
                raise ValueError("No extractable text found in document.")

            embedding_provider = get_embedding_provider("openai")
            vectors = await embedding_provider.embed(chunks)

            for index, (chunk_content, vector) in enumerate(
                zip(chunks, vectors)
            ):
                await knowledge_chunk_repository.create(
                    db,
                    KnowledgeChunk(
                        document_id=document.id,
                        organization_id=organization_id,
                        chunk_index=index,
                        content=chunk_content,
                        embedding=vector,
                        embedding_model=settings.EMBEDDING_MODEL,
                    ),
                )

            document.processing_status = "completed"
        except Exception as exc:
            document.processing_status = "failed"
            document.error_message = str(exc)

            return await knowledge_document_repository.update(db, document)

        # Visual indexing is additive and deliberately non-fatal. The
        # text index above is what the product has always relied on; if
        # rasterizing or embedding pages fails — no GPU, an image-only
        # PDF, an unreachable object store — the document must still be
        # searchable by text rather than being marked failed wholesale.
        # The reason is recorded so the gap is visible rather than
        # guessed at.
        if settings.VISUAL_RAG_ENABLED and content_type == "application/pdf":
            try:
                result = await visual_service.index_document(
                    db,
                    document=document,
                    organization_id=organization_id,
                    file_bytes=file_bytes,
                )
                logger.info(
                    "Visual index for %s: %d pages, %d embedded via %s.",
                    filename,
                    result.pages_indexed,
                    result.pages_embedded,
                    result.provider,
                )
            except Exception as exc:
                logger.warning(
                    "Visual indexing skipped for %s: %s", filename, exc
                )
                document.visual_index_error = str(exc)

        return await knowledge_document_repository.update(db, document)

    async def search(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        query: str,
        top_k: int = 5,
    ) -> list[retrieval.ChunkMatch]:

        embedding_provider = get_embedding_provider("openai")

        # ~3s of a measured ~3.5s search was this one API round trip, so
        # a repeat question should not pay for it twice. Cached on
        # (model, text); ingestion at upload_document deliberately is
        # not, since each chunk is embedded exactly once.
        query_embedding = embedding_cache.get(settings.EMBEDDING_MODEL, query)

        if query_embedding is not None:
            return await retrieval.search(
                db,
                organization_id=organization_id,
                query_embedding=query_embedding,
                top_k=top_k,
            )

        try:
            [query_embedding] = await embedding_provider.embed([query])

            embedding_cache.put(
                settings.EMBEDDING_MODEL, query, query_embedding
            )
        except Exception as exc:
            # Mirrors upload_document's own broad catch around the same
            # embedding call — any failure here (missing API key, rate
            # limit, network) means "knowledge search isn't available right
            # now," not a 500 with no explanation.
            raise KnowledgeServiceError(
                "Knowledge base search is unavailable — the embedding "
                "provider isn't configured or reachable. Contact your "
                "administrator.",
            ) from exc

        return await retrieval.search(
            db,
            organization_id=organization_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )

    async def _search_pages(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        query: str,
    ) -> list:
        """Visual matches, or none — never an error.

        Visual search is an enhancement to `ask`, so every way it can be
        unavailable (disabled, no GPU, no provider key, nothing indexed
        yet) has to degrade to text-only rather than failing a question
        the text index could have answered. The reason is logged, not
        raised.
        """

        if not settings.VISUAL_RAG_ENABLED:
            return []

        availability = visual_rag_availability()

        if not availability.available:
            logger.debug("Visual search unavailable: %s", availability.reason)
            return []

        try:
            return await visual_service.search(
                db, organization_id=organization_id, query=query
            )
        except Exception as exc:
            logger.warning("Visual search failed, answering from text: %s", exc)
            return []

    async def _page_attachments(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        page_matches: list,
    ) -> list[AttachmentInput]:
        """Load matched page images as chat attachments.

        A page whose image cannot be fetched is dropped rather than
        failing the question — the row and the object can diverge (a
        restored database, a lifecycle-expired object), and the other
        pages are still good evidence.
        """

        attachments: list[AttachmentInput] = []

        for match in page_matches:
            try:
                image = await visual_service.load_image(
                    db, organization_id=organization_id, page=match.page
                )
            except Exception as exc:
                logger.warning(
                    "Page image %s unavailable, skipping: %s", match.page.id, exc
                )
                continue

            # The extension is what `process_attachments` reads to pick
            # a media type; the stem is what the model sees when asked
            # to cite its source, so it names the document and page.
            filename = (
                f"{match.page.document.filename} p{match.page.page_number}.jpg"
            )

            attachments.append(
                AttachmentInput(
                    filename=filename,
                    content_type="image/jpeg",
                    data=base64.b64encode(image).decode("ascii"),
                )
            )

        return attachments

    async def ask(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        conversation_id: uuid.UUID | None = None,
        agent: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AskResult:

        matches = await self.search(
            db,
            organization_id=organization_id,
            query=query,
        )

        page_matches = await self._search_pages(
            db, organization_id=organization_id, query=query
        )

        attachments = await self._page_attachments(
            db, organization_id=organization_id, page_matches=page_matches
        )

        system_prompt = None

        if matches:
            context = "\n\n".join(
                f"[Source: {match.chunk.document.filename}, "
                f"chunk {match.chunk.chunk_index}]\n{match.chunk.content}"
                for match in matches
            )

            system_prompt = (
                "In addition to any TM1 tools available to you, use the "
                "following context from the organization's knowledge base "
                "to answer the question. If neither the context nor a tool "
                "call can answer it, say so rather than guessing.\n\n"
                f"{context}"
            )

        if attachments:
            # Without this the model receives images with no idea what
            # they are or that it may cite them, and tends to describe
            # them ("the image shows a table...") instead of answering
            # from them. Naming the page number is what makes a citation
            # checkable by the reader.
            pages_note = "\n".join(
                f"- Image {index}: {match.page.document.filename}, "
                f"page {match.page.page_number}"
                for index, match in enumerate(page_matches, start=1)
            )

            visual_context = (
                "The attached images are pages from the organization's "
                "documents, retrieved as relevant to this question. Read "
                "them directly — charts, tables and figures on them are "
                "readable as shown, and are often the only place the "
                "answer exists. Cite the page you used.\n\n"
                f"{pages_note}"
            )

            system_prompt = (
                f"{system_prompt}\n\n{visual_context}"
                if system_prompt
                else visual_context
            )

        # Passing both `system` (the retrieved document context) and
        # `agent` is what actually combines the two knowledge sources: the
        # persona brings live TM1 tool access, and _build_tool_system_prompt
        # concatenates persona.system_prompt + this `system` override into
        # one prompt (see AIOrchestrator._build_tool_system_prompt).
        chat_result = await ai_orchestrator.chat(
            db,
            organization_id=organization_id,
            user_id=user_id,
            message=query,
            conversation_id=conversation_id,
            system=system_prompt,
            agent=agent,
            enable_tools=agent is not None,
            attachments=attachments or None,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        citations = [
            Citation(
                document_id=match.chunk.document_id,
                filename=match.chunk.document.filename,
                chunk_index=match.chunk.chunk_index,
                score=match.score,
            )
            for match in matches
        ]

        page_citations = [
            PageCitation(
                page_id=match.page.id,
                document_id=match.page.document_id,
                filename=match.page.document.filename,
                page_number=match.page.page_number,
                score=match.score,
            )
            for match in page_matches
        ]

        return AskResult(chat_result, citations, page_citations)


knowledge_service = KnowledgeService()
