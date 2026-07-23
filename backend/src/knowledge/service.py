import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.orchestrator import ChatResult, ai_orchestrator
from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.database.models.knowledge_chunk import KnowledgeChunk
from src.database.models.knowledge_document import KnowledgeDocument
from src.knowledge import retrieval
from src.knowledge.chunking import chunk_text
from src.knowledge.embeddings.registry import get_embedding_provider
from src.knowledge.exceptions import KnowledgeServiceError
from src.knowledge.loaders.registry import get_loader
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


class AskResult:

    def __init__(self, chat_result: ChatResult, citations: list[Citation]):
        self.chat_result = chat_result
        self.citations = citations


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

    async def search(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        query: str,
        top_k: int = 5,
    ) -> list[retrieval.ChunkMatch]:

        embedding_provider = get_embedding_provider("openai")

        try:
            [query_embedding] = await embedding_provider.embed([query])
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

        return AskResult(chat_result, citations)


knowledge_service = KnowledgeService()
