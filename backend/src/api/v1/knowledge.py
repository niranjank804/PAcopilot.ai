import uuid

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.api.dependencies.rate_limit import ai_rate_limited
from src.core.exceptions import ValidationException
from src.database.session import get_db
from src.errors.classifier import classify_error
from src.knowledge.loaders.registry import resolve_content_type
from src.core.exceptions import NotFoundException
from src.knowledge.service import knowledge_service
from src.knowledge.visual.providers.registry import (
    get_visual_provider,
    visual_rag_availability,
)
from src.knowledge.visual.service import visual_service
from src.repositories.visual_page_repository import visual_page_repository
from src.core.config import settings
from src.schemas.ai import UsageResponse
from src.schemas.auth import UserResponse
from src.schemas.knowledge import (
    AskRequest,
    AskResponse,
    CitationResponse,
    DocumentResponse,
    ExplainErrorRequest,
    ExplainErrorResponse,
    PageCitationResponse,
    SearchRequest,
    SearchResultItem,
    VisualStatusResponse,
)
from src.schemas.response import ApiResponse

router = APIRouter(
    prefix="/knowledge",
    tags=["Knowledge"],
)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


@router.post(
    "/documents",
    response_model=ApiResponse[DocumentResponse],
    status_code=201,
)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.write")),
):
    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationException("File exceeds the 50MB upload limit.")

    content_type = resolve_content_type(file.filename or "", file.content_type)

    document = await knowledge_service.upload_document(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        filename=file.filename or "untitled",
        content_type=content_type,
        file_bytes=file_bytes,
    )

    return ApiResponse(success=True, data=DocumentResponse.model_validate(document))


@router.get(
    "/documents",
    response_model=ApiResponse[list[DocumentResponse]],
)
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    documents = await knowledge_service.list_documents(
        db,
        current_user.organization_id,
    )

    return ApiResponse(
        success=True,
        data=[DocumentResponse.model_validate(doc) for doc in documents],
    )


@router.get(
    "/documents/{document_id}",
    response_model=ApiResponse[DocumentResponse],
)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    document = await knowledge_service.get_document(
        db,
        document_id,
        current_user.organization_id,
    )

    return ApiResponse(success=True, data=DocumentResponse.model_validate(document))


@router.delete(
    "/documents/{document_id}",
    response_model=ApiResponse[None],
)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.write")),
):
    await knowledge_service.delete_document(
        db,
        document_id,
        current_user.organization_id,
    )

    return ApiResponse(success=True, data=None)


@router.post(
    "/search",
    response_model=ApiResponse[list[SearchResultItem]],
)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    matches = await knowledge_service.search(
        db,
        organization_id=current_user.organization_id,
        query=request.query,
        top_k=request.top_k,
    )

    return ApiResponse(
        success=True,
        data=[
            SearchResultItem(
                document_id=match.chunk.document_id,
                filename=match.chunk.document.filename,
                chunk_index=match.chunk.chunk_index,
                content=match.chunk.content,
                score=match.score,
            )
            for match in matches
        ],
    )


@router.post(
    "/ask",
    response_model=ApiResponse[AskResponse],
)
async def ask(
    request: AskRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
    _: UserResponse = Depends(ai_rate_limited),
):
    ip_address, user_agent = _client_context(http_request)

    result = await knowledge_service.ask(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        query=request.query,
        conversation_id=request.conversation_id,
        agent=request.agent,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    chat_result = result.chat_result

    return ApiResponse(
        success=True,
        data=AskResponse(
            conversation_id=chat_result.conversation_id,
            message_id=chat_result.message_id,
            content=chat_result.content,
            model=chat_result.model,
            usage=UsageResponse(
                prompt_tokens=chat_result.usage.input_tokens,
                completion_tokens=chat_result.usage.output_tokens,
                total_tokens=(
                    chat_result.usage.input_tokens
                    + chat_result.usage.output_tokens
                ),
                estimated_cost_usd=float(chat_result.estimated_cost_usd),
            ),
            citations=[
                CitationResponse(
                    document_id=citation.document_id,
                    filename=citation.filename,
                    chunk_index=citation.chunk_index,
                    score=citation.score,
                )
                for citation in result.citations
            ],
            page_citations=[
                PageCitationResponse(
                    page_id=citation.page_id,
                    document_id=citation.document_id,
                    filename=citation.filename,
                    page_number=citation.page_number,
                    score=citation.score,
                )
                for citation in result.page_citations
            ],
        ),
    )


@router.post(
    "/explain-error",
    response_model=ApiResponse[ExplainErrorResponse],
)
async def explain_error(
    request: ExplainErrorRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
    _: UserResponse = Depends(ai_rate_limited),
):
    ip_address, user_agent = _client_context(http_request)

    classification = classify_error(request.error_text)

    result = await knowledge_service.ask(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        query=(
            "Explain this TM1 error and give a step-by-step fix:\n\n"
            f"{request.error_text}"
        ),
        agent="troubleshooter",
        ip_address=ip_address,
        user_agent=user_agent,
    )

    chat_result = result.chat_result

    return ApiResponse(
        success=True,
        data=ExplainErrorResponse(
            error_type=classification.error_type,
            severity=classification.severity,
            conversation_id=chat_result.conversation_id,
            message_id=chat_result.message_id,
            content=chat_result.content,
            model=chat_result.model,
            usage=UsageResponse(
                prompt_tokens=chat_result.usage.input_tokens,
                completion_tokens=chat_result.usage.output_tokens,
                total_tokens=(
                    chat_result.usage.input_tokens
                    + chat_result.usage.output_tokens
                ),
                estimated_cost_usd=float(chat_result.estimated_cost_usd),
            ),
            citations=[
                CitationResponse(
                    document_id=citation.document_id,
                    filename=citation.filename,
                    chunk_index=citation.chunk_index,
                    score=citation.score,
                )
                for citation in result.citations
            ],
        ),
    )


@router.get(
    "/visual/status",
    response_model=ApiResponse[VisualStatusResponse],
)
async def visual_status(
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    """Whether visual search can run here, and why not if it cannot.

    Visual indexing degrades silently by design — a document must stay
    searchable by text when there is no GPU — which means without an
    endpoint like this the degradation is invisible, and an
    administrator has no way to tell "no relevant pages" apart from
    "this never worked".
    """

    availability = visual_rag_availability()

    return ApiResponse(
        success=True,
        data=VisualStatusResponse(
            enabled=settings.VISUAL_RAG_ENABLED,
            provider=get_visual_provider().name,
            available=availability.available,
            reason=availability.reason,
        ),
    )


@router.get("/pages/{page_id}/image")
async def get_page_image(
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("knowledge.read")),
):
    """The rendered page behind a citation, so a reader can check it.

    Two independent tenancy checks, deliberately. The row is compared
    against the caller's organization here, and the storage backend
    re-checks the key prefix on the way to S3 — because a citation id is
    the kind of value that ends up in a URL, and one check is one
    forgotten `if` away from serving another tenant's page.
    """

    page = await visual_page_repository.get_by_id(db, page_id)

    if page is None or page.organization_id != current_user.organization_id:
        # 404 rather than 403: whether a page id exists is itself
        # information about another organization's documents.
        raise NotFoundException("Page not found.")

    image = await visual_service.load_image(
        db, organization_id=current_user.organization_id, page=page
    )

    return Response(
        content=image,
        media_type="image/jpeg",
        headers={
            # Immutable: a page image is derived from a specific upload
            # and never rewritten in place. private, because it is
            # tenant data and must not be held by a shared proxy.
            "Cache-Control": "private, max-age=3600, immutable",
        },
    )
