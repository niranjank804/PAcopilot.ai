import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.agents.base import AgentPersona
from src.ai.agents.registry import get_agent
from src.ai.attachment_processing import process_attachments
from src.ai.pricing import estimate_cost
from src.ai.providers.base import AIProvider
from src.ai.registry import get_provider
from src.ai.schemas import (
    Attachment,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    OrchestratedStreamEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
)
from src.ai.tools.registry import get_tool, list_tools
from src.core.config import settings
from src.core.exceptions import (
    AppException,
    NotFoundException,
    QuotaExceededException,
    ValidationException,
)
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_message import AIMessage
from src.database.models.ai_tool_execution import AIToolExecution
from src.database.models.ai_usage import AIUsage
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_message_repository import ai_message_repository
from src.repositories.ai_tool_execution_repository import (
    ai_tool_execution_repository,
)
from src.repositories.ai_usage_repository import ai_usage_repository
from src.schemas.ai import AttachmentInput
from src.services.audit_service import audit_service
from src.tm1.resilience import CircuitState, peek_circuit_breaker
from src.tm1.service import tm1_integration_service

MAX_TOOL_ROUNDS = 5
# Hard cap on any persona's max_tool_rounds override, independent of what a
# persona definition configures — a misconfigured persona can't hang a
# request. Mirrors MAX_TRAVERSAL_NODES in the dependency analyzer.
MAX_TOOL_ROUNDS_CEILING = 15


def _resolve_max_tool_rounds(persona: AgentPersona | None) -> int:
    if persona is not None and persona.max_tool_rounds:
        return min(persona.max_tool_rounds, MAX_TOOL_ROUNDS_CEILING)

    return MAX_TOOL_ROUNDS


class ChatResult:

    def __init__(
        self,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        content: str,
        model: str,
        usage: Usage,
        estimated_cost_usd,
    ):
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.content = content
        self.model = model
        self.usage = usage
        self.estimated_cost_usd = estimated_cost_usd


class AIOrchestrator:

    async def _get_or_create_conversation(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        message: str,
    ) -> AIConversation:

        if conversation_id is not None:
            conversation = await ai_conversation_repository.get_by_id(
                db,
                conversation_id,
            )

            if conversation is None or conversation.user_id != user_id:
                raise NotFoundException(
                    "Conversation not found."
                )

            return conversation

        title = message.strip().splitlines()[0][:60] if message.strip() else None

        conversation = AIConversation(
            organization_id=organization_id,
            user_id=user_id,
            title=title,
        )

        return await ai_conversation_repository.create(db, conversation)

    async def _build_history(
        self,
        db: AsyncSession,
        conversation: AIConversation,
    ) -> list[ChatMessage]:

        messages = await ai_message_repository.list_by_conversation(
            db,
            conversation.id,
        )

        return [
            ChatMessage(role=message.role, content=message.content)
            for message in messages
        ]

    async def _build_tool_system_prompt(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        system: str | None,
        persona: AgentPersona | None = None,
    ) -> str | None:

        connections = await tm1_integration_service.list_connections(
            db,
            organization_id,
        )

        # Skip connections whose circuit breaker is currently OPEN — agents
        # were observed burning a tool round probing known-dead servers.
        reachable = [
            connection
            for connection in connections
            if not (
                (breaker := peek_circuit_breaker(connection.id)) is not None
                and breaker.state == CircuitState.OPEN
            )
        ]

        if reachable:
            connection_lines = "\n".join(
                f"- id={connection.id}, name={connection.name}, "
                f"address={connection.address}"
                for connection in reachable
            )
            connection_context = (
                "Available TM1 connections (use these ids as the "
                f"connection_id tool argument):\n{connection_lines}\n\n"
                "For survey-style questions (e.g. 'which processes update "
                "cube X', 'what depends on Y'), prefer one graph query "
                "(get_object_relationships, find_dependents) over iterating "
                "objects one by one."
            )
        else:
            connection_context = (
                "No reachable TM1 connections are configured for this "
                "organization."
            )

        safety_notes_block = None

        if persona is not None and persona.safety_notes:
            bullets = "\n".join(f"- {note}" for note in persona.safety_notes)
            safety_notes_block = f"Safety rules:\n{bullets}"

        parts = [
            persona.system_prompt if persona is not None else None,
            safety_notes_block,
            system,
            connection_context,
        ]

        return "\n\n".join(part for part in parts if part)

    def _prepare_user_message(
        self,
        message: str,
        attachments: list[AttachmentInput] | None,
    ) -> tuple[str, str, list[Attachment]]:
        """Returns (content_for_ai, content_to_persist, native_attachments).

        Images/PDFs are sent to Claude natively (real vision/document
        understanding) but their binary is never persisted to AIMessage —
        only a filename marker is, keeping conversation history a plain
        text log. DOCX text IS persisted (it's just text, no bloat
        concern) since it's folded directly into the message content.
        """

        if not attachments:
            return message, message, []

        native_attachments, extracted_text = process_attachments(attachments)

        content_for_ai = (
            f"{message}\n\n{extracted_text}" if message and extracted_text else
            extracted_text or message
        )

        content_to_persist = content_for_ai

        if native_attachments:
            marker = ", ".join(a.filename for a in native_attachments)
            content_to_persist = f"{content_to_persist}\n\n[Attached: {marker}]"

        return content_for_ai, content_to_persist, native_attachments

    async def _record_tool_execution(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        tool_name: str,
        arguments: dict,
        status: str,
        result_summary: str | None,
        duration_ms: int,
        error_message: str | None,
    ) -> None:

        await ai_tool_execution_repository.create(
            db,
            AIToolExecution(
                conversation_id=conversation_id,
                organization_id=organization_id,
                user_id=user_id,
                tool_name=tool_name,
                arguments=arguments,
                status=status,
                result_summary=result_summary,
                duration_ms=duration_ms,
                error_message=error_message,
            ),
        )

    async def _execute_tool_call(
        self,
        db: AsyncSession,
        tool_call: ToolCall,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        allowed_tools: list[str] | None = None,
    ) -> ToolResult:

        start = time.monotonic()

        if allowed_tools is not None and tool_call.name not in allowed_tools:
            error_message = (
                f"Tool '{tool_call.name}' is not available to this agent."
            )

            await self._record_tool_execution(
                db,
                conversation_id=conversation_id,
                organization_id=organization_id,
                user_id=user_id,
                tool_name=tool_call.name,
                arguments=tool_call.input,
                status="error",
                result_summary=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=error_message,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                content=error_message,
                is_error=True,
            )

        tool = get_tool(tool_call.name)

        if tool is None:
            error_message = f"Unknown tool: {tool_call.name}"

            await self._record_tool_execution(
                db,
                conversation_id=conversation_id,
                organization_id=organization_id,
                user_id=user_id,
                tool_name=tool_call.name,
                arguments=tool_call.input,
                status="error",
                result_summary=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=error_message,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                content=error_message,
                is_error=True,
            )

        try:
            result = await tool.execute(
                db,
                organization_id=organization_id,
                user_id=user_id,
                **tool_call.input,
            )
        except AppException as exc:
            await self._record_tool_execution(
                db,
                conversation_id=conversation_id,
                organization_id=organization_id,
                user_id=user_id,
                tool_name=tool_call.name,
                arguments=tool_call.input,
                status="error",
                result_summary=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_message=exc.message,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                content=exc.message,
                is_error=True,
            )

        await self._record_tool_execution(
            db,
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            tool_name=tool_call.name,
            arguments=tool_call.input,
            status="success",
            result_summary=result[:500],
            duration_ms=int((time.monotonic() - start) * 1000),
            error_message=None,
        )

        return ToolResult(
            tool_call_id=tool_call.id,
            content=result,
            is_error=False,
        )

    async def _run_tool_loop(
        self,
        db: AsyncSession,
        *,
        provider: AIProvider,
        history: list[ChatMessage],
        model: str,
        system: str | None,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        allowed_tools: list[str] | None = None,
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> tuple[ChatResponse, Usage]:

        available_tools = list_tools()

        if allowed_tools is not None:
            available_tools = [
                tool for tool in available_tools if tool.name in allowed_tools
            ]

        tools = [tool.to_definition() for tool in available_tools]
        total_input_tokens = 0
        total_output_tokens = 0
        response: ChatResponse | None = None

        for _ in range(max_rounds):
            request = ChatRequest(
                messages=history,
                model=model,
                system=system,
                tools=tools,
            )
            response = await provider.chat(request)

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            if response.stop_reason != "tool_use" or not response.tool_calls:
                break

            history.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            tool_results = [
                await self._execute_tool_call(
                    db,
                    tool_call,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    allowed_tools=allowed_tools,
                )
                for tool_call in response.tool_calls
            ]

            history.append(
                ChatMessage(
                    role="user",
                    content="",
                    tool_results=tool_results,
                )
            )

        return response, Usage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    async def _check_usage_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:

        if settings.AI_MONTHLY_TOKEN_LIMIT is None:
            return

        now = datetime.now(timezone.utc)
        start_of_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        total_tokens = await ai_usage_repository.get_total_tokens_since(
            db, organization_id, start_of_month
        )

        if total_tokens >= settings.AI_MONTHLY_TOKEN_LIMIT:
            raise QuotaExceededException(
                "Monthly AI usage quota exceeded for this organization."
            )

    async def chat(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        message: str,
        conversation_id: uuid.UUID | None = None,
        model: str | None = None,
        system: str | None = None,
        enable_tools: bool = False,
        agent: str | None = None,
        attachments: list[AttachmentInput] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ChatResult:

        persona: AgentPersona | None = None

        if agent is not None:
            persona = get_agent(agent)

            if persona is None:
                raise ValidationException(f"Unknown agent: {agent}")

            enable_tools = True

        await self._check_usage_quota(db, organization_id)

        conversation = await self._get_or_create_conversation(
            db,
            organization_id,
            user_id,
            conversation_id,
            message,
        )

        content_for_ai, content_to_persist, native_attachments = (
            self._prepare_user_message(message, attachments)
        )

        history = await self._build_history(db, conversation)
        history.append(
            ChatMessage(
                role="user",
                content=content_for_ai,
                attachments=native_attachments or None,
            )
        )

        await ai_message_repository.create(
            db,
            AIMessage(
                conversation_id=conversation.id,
                role="user",
                content=content_to_persist,
            ),
        )

        resolved_model = model or settings.AI_DEFAULT_MODEL
        provider = get_provider("anthropic")

        start = time.monotonic()

        if enable_tools:
            tool_system = await self._build_tool_system_prompt(
                db,
                organization_id,
                system,
                persona,
            )
            response, usage = await self._run_tool_loop(
                db,
                provider=provider,
                history=history,
                model=resolved_model,
                system=tool_system,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation.id,
                allowed_tools=persona.tool_names if persona is not None else None,
                max_rounds=_resolve_max_tool_rounds(persona),
            )
        else:
            request = ChatRequest(
                messages=history,
                model=resolved_model,
                system=system,
            )
            response = await provider.chat(request)
            usage = response.usage

        latency_ms = int((time.monotonic() - start) * 1000)

        assistant_message = await ai_message_repository.create(
            db,
            AIMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=response.content,
            ),
        )

        cost = estimate_cost(resolved_model, usage)

        await ai_usage_repository.create(
            db,
            AIUsage(
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                organization_id=organization_id,
                user_id=user_id,
                provider="anthropic",
                model=resolved_model,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=(
                    usage.input_tokens + usage.output_tokens
                ),
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
            ),
        )

        await audit_service.log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="chat",
            entity="AIConversation",
            entity_id=conversation.id,
            new_values={
                "model": resolved_model,
                "total_tokens": usage.input_tokens + usage.output_tokens,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return ChatResult(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            content=response.content,
            model=resolved_model,
            usage=usage,
            estimated_cost_usd=cost,
        )

    async def stream_chat(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        message: str,
        conversation_id: uuid.UUID | None = None,
        model: str | None = None,
        system: str | None = None,
        enable_tools: bool = False,
        agent: str | None = None,
        attachments: list[AttachmentInput] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AsyncIterator[OrchestratedStreamEvent]:

        persona: AgentPersona | None = None

        if agent is not None:
            persona = get_agent(agent)

            if persona is None:
                raise ValidationException(f"Unknown agent: {agent}")

            enable_tools = True

        await self._check_usage_quota(db, organization_id)

        conversation = await self._get_or_create_conversation(
            db,
            organization_id,
            user_id,
            conversation_id,
            message,
        )

        content_for_ai, content_to_persist, native_attachments = (
            self._prepare_user_message(message, attachments)
        )

        history = await self._build_history(db, conversation)
        history.append(
            ChatMessage(
                role="user",
                content=content_for_ai,
                attachments=native_attachments or None,
            )
        )

        await ai_message_repository.create(
            db,
            AIMessage(
                conversation_id=conversation.id,
                role="user",
                content=content_to_persist,
            ),
        )

        resolved_model = model or settings.AI_DEFAULT_MODEL
        provider = get_provider("anthropic")

        tools: list[ToolDefinition] | None = None
        resolved_system = system
        allowed_tools: list[str] | None = None

        if enable_tools:
            resolved_system = await self._build_tool_system_prompt(
                db,
                organization_id,
                system,
                persona,
            )
            allowed_tools = persona.tool_names if persona is not None else None

            available_tools = list_tools()

            if allowed_tools is not None:
                available_tools = [
                    tool for tool in available_tools if tool.name in allowed_tools
                ]

            tools = [tool.to_definition() for tool in available_tools]

        total_input_tokens = 0
        total_output_tokens = 0
        final_content_parts: list[str] = []

        start = time.monotonic()

        max_rounds = _resolve_max_tool_rounds(persona) if enable_tools else 1

        for _ in range(max_rounds):
            round_content_parts: list[str] = []
            round_usage: Usage | None = None
            round_tool_calls: list[ToolCall] | None = None
            round_stop_reason: str | None = None

            request = ChatRequest(
                messages=history,
                model=resolved_model,
                system=resolved_system,
                tools=tools,
            )

            async for event in provider.stream_chat(request):
                if event.type == "text_delta":
                    round_content_parts.append(event.text or "")

                    yield OrchestratedStreamEvent(
                        type="text_delta",
                        text=event.text,
                    )
                elif event.type == "message_stop":
                    round_usage = event.usage
                    round_tool_calls = event.tool_calls
                    round_stop_reason = event.stop_reason

            if round_usage is not None:
                total_input_tokens += round_usage.input_tokens
                total_output_tokens += round_usage.output_tokens

            final_content_parts = round_content_parts

            if (
                not enable_tools
                or round_stop_reason != "tool_use"
                or not round_tool_calls
            ):
                break

            history.append(
                ChatMessage(
                    role="assistant",
                    content="".join(round_content_parts),
                    tool_calls=round_tool_calls,
                )
            )

            tool_results: list[ToolResult] = []

            for tool_call in round_tool_calls:
                result = await self._execute_tool_call(
                    db,
                    tool_call,
                    organization_id=organization_id,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    allowed_tools=allowed_tools,
                )
                tool_results.append(result)

                yield OrchestratedStreamEvent(
                    type="tool_call",
                    tool_name=tool_call.name,
                    tool_status="error" if result.is_error else "success",
                )

            history.append(
                ChatMessage(
                    role="user",
                    content="",
                    tool_results=tool_results,
                )
            )

        latency_ms = int((time.monotonic() - start) * 1000)

        assistant_message = await ai_message_repository.create(
            db,
            AIMessage(
                conversation_id=conversation.id,
                role="assistant",
                content="".join(final_content_parts),
            ),
        )

        usage = Usage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
        cost = estimate_cost(resolved_model, usage)

        await ai_usage_repository.create(
            db,
            AIUsage(
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                organization_id=organization_id,
                user_id=user_id,
                provider="anthropic",
                model=resolved_model,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
            ),
        )

        await audit_service.log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="chat_stream",
            entity="AIConversation",
            entity_id=conversation.id,
            new_values={
                "model": resolved_model,
                "total_tokens": usage.input_tokens + usage.output_tokens,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        yield OrchestratedStreamEvent(
            type="done",
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            usage=usage,
            estimated_cost_usd=float(cost),
        )


ai_orchestrator = AIOrchestrator()
