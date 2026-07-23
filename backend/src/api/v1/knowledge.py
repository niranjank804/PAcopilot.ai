import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.core.exceptions import ValidationException
from src.database.session import get_db
from src.errors.classifier import classify_error
from src.knowledge.loaders.registry import resolve_content_type
from src.knowledge.service import knowledge_service
from src.schemas.ai import UsageResponse
from src.schemas.auth import UserResponse
from src.schemas.knowledge import (
    AskRequest,
    AskResponse,
    CitationResponse,
    DocumentResponse,
    ExplainErrorRequest,
    ExplainErrorResponse,
    SearchRequest,
    SearchResultItem,
)
from src.schemas.response import ApiResponse

router = APIRouter(
    prefix="/knowledge",
    tags=["Knowledge"],
)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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
        raise ValidationException("File exceeds the 20MB upload limit.")

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
