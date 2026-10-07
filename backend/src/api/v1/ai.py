import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.agents.registry import list_agents
from src.ai.exceptions import AIProviderError
from src.ai.uploaded_attachments import resolve_uploaded_attachments
from src.ai.orchestrator import _resolve_max_tool_rounds, ai_orchestrator
from src.api.dependencies.permissions import require_permission
from src.api.dependencies.rate_limit import ai_rate_limited
from src.core.exceptions import (
    NotFoundException,
    QuotaExceededException,
    ValidationException,
)
from src.core.sse import with_heartbeat
from src.database.models.ai_conversation import AIConversation
from src.database.session import get_db
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_message_repository import ai_message_repository
from src.repositories.ai_tool_execution_repository import (
    ai_tool_execution_repository,
)
from src.schemas.ai import (
    AgentResponse,
    ChatRequest,
    ChatResponse,
    ConversationRenameRequest,
    ConversationSummary,
    ConversationVisibilityRequest,
    MessageResponse,
    ToolExecutionResponse,
    UsageResponse,
)
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.audit_service import audit_service
from src.services.work_item_service import can_read_conversation

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
)

# Well inside the idle limits proxies commonly apply, and rare enough to be
# free: a streamed answer that is producing text never sends one.
STREAM_HEARTBEAT_SECONDS = 15.0


async def _get_owned_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AIConversation:
    conversation = await ai_conversation_repository.get_by_id(db, conversation_id)

    if conversation is None or conversation.user_id != user_id:
        raise NotFoundException("Conversation not found.")

    return conversation


async def _get_readable_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    current_user: UserResponse,
) -> AIConversation:
    """The owner's conversation, or one its owner shared with the
    organization. Reading only: sending, renaming, sharing and deleting
    stay with the owner (`_get_owned_conversation`)."""

    conversation = await ai_conversation_repository.get_by_id(db, conversation_id)

    if conversation is None or not can_read_conversation(
        conversation, current_user.organization_id, current_user.id
    ):
        raise NotFoundException("Conversation not found.")

    return conversation


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


@router.post(
    "/chat",
    response_model=ApiResponse[ChatResponse],
)
async def chat(
    request: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
    _: UserResponse = Depends(ai_rate_limited),
):
    ip_address, user_agent = _client_context(http_request)

    result = await ai_orchestrator.chat(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        message=request.message,
        conversation_id=request.conversation_id,
        model=request.model,
        enable_tools=request.enable_tools,
        agent=request.agent,
        connection_id=request.connection_id,
        attachments=await resolve_uploaded_attachments(
                request.attachments, current_user.organization_id
            ),
        ip_address=ip_address,
        user_agent=user_agent,
        task_id=request.task_id,
        new_task=request.new_task,
    )

    return ApiResponse(
        success=True,
        data=ChatResponse(
            conversation_id=result.conversation_id,
            message_id=result.message_id,
            content=result.content,
            model=result.model,
            task=result.task,
            usage=UsageResponse(
                prompt_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                total_tokens=(
                    result.usage.input_tokens + result.usage.output_tokens
                ),
                estimated_cost_usd=float(result.estimated_cost_usd),
            ),
        ),
    )


@router.get(
    "/agents",
    response_model=ApiResponse[list[AgentResponse]],
)
async def list_ai_agents(
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    return ApiResponse(
        success=True,
        data=[
            AgentResponse(
                name=agent.name,
                description=agent.description,
                max_tool_rounds=_resolve_max_tool_rounds(agent),
                tool_names=agent.tool_names,
                safety_notes=agent.safety_notes,
            )
            for agent in list_agents()
        ],
    )


@router.get(
    "/conversations",
    response_model=ApiResponse[list[ConversationSummary]],
)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    conversations = await ai_conversation_repository.list_by_user(
        db,
        current_user.id,
    )

    return ApiResponse(
        success=True,
        data=[ConversationSummary.model_validate(c) for c in conversations],
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ApiResponse[list[MessageResponse]],
)
async def list_conversation_messages(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    await _get_readable_conversation(db, conversation_id, current_user)

    messages = await ai_message_repository.list_by_conversation(
        db,
        conversation_id,
    )

    return ApiResponse(
        success=True,
        data=[MessageResponse.model_validate(m) for m in messages],
    )


@router.get(
    "/conversations/{conversation_id}/tool-executions",
    response_model=ApiResponse[list[ToolExecutionResponse]],
)
async def list_conversation_tool_executions(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    await _get_readable_conversation(db, conversation_id, current_user)

    executions = await ai_tool_execution_repository.list_by_conversation(
        db,
        conversation_id,
    )

    return ApiResponse(
        success=True,
        data=[ToolExecutionResponse.model_validate(e) for e in executions],
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ConversationSummary],
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    request: ConversationRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)

    conversation = await ai_conversation_repository.update_title(
        db,
        conversation,
        request.title,
    )

    return ApiResponse(success=True, data=ConversationSummary.model_validate(conversation))


@router.put(
    "/conversations/{conversation_id}/visibility",
    response_model=ApiResponse[ConversationSummary],
)
async def set_conversation_visibility(
    conversation_id: uuid.UUID,
    request: ConversationVisibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    """Share a conversation with the organization (read-only for others),
    or make it private again. Only its owner can."""

    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)

    if conversation.visibility != request.visibility:
        old = conversation.visibility
        conversation.visibility = request.visibility
        await db.flush()
        await db.refresh(conversation)
        await audit_service.log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="conversation_shared" if request.visibility == "organization" else "conversation_unshared",
            entity="AIConversation",
            entity_id=conversation.id,
            old_values={"visibility": old},
            new_values={"visibility": request.visibility},
        )

    return ApiResponse(success=True, data=ConversationSummary.model_validate(conversation))


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[None],
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user.id)

    await ai_conversation_repository.delete(db, conversation)

    return ApiResponse(success=True, data=None)


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("ai.chat")),
    _: UserResponse = Depends(ai_rate_limited),
):
    ip_address, user_agent = _client_context(http_request)

    async def event_source():
        try:
            async for event in ai_orchestrator.stream_chat(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                message=request.message,
                conversation_id=request.conversation_id,
                model=request.model,
                enable_tools=request.enable_tools,
                agent=request.agent,
                connection_id=request.connection_id,
                attachments=await resolve_uploaded_attachments(
                request.attachments, current_user.organization_id
            ),
                ip_address=ip_address,
                user_agent=user_agent,
                task_id=request.task_id,
                new_task=request.new_task,
            ):
                yield f"data: {event.model_dump_json()}\n\n"
        except (AIProviderError, ValidationException, QuotaExceededException) as exc:
            payload = json.dumps({"type": "error", "message": exc.message})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        with_heartbeat(event_source(), STREAM_HEARTBEAT_SECONDS),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Asks any buffering proxy in front of the app to pass events
            # through as they are written instead of holding them back.
            "X-Accel-Buffering": "no",
        },
    )
