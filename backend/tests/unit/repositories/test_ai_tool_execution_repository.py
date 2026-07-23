from datetime import datetime, timedelta, timezone

import pytest

from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_tool_execution import AIToolExecution
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from tests.fixtures.factories import create_organization, create_user


async def _create_conversation(db_session, organization_id, user_id):
    return await ai_conversation_repository.create(
        db_session,
        AIConversation(organization_id=organization_id, user_id=user_id),
    )


async def _create_execution(
    db_session,
    conversation,
    organization_id,
    user_id,
    tool_name,
    status,
    duration_ms,
):
    return await ai_tool_execution_repository.create(
        db_session,
        AIToolExecution(
            conversation_id=conversation.id,
            organization_id=organization_id,
            user_id=user_id,
            tool_name=tool_name,
            arguments={},
            status=status,
            result_summary=None,
            duration_ms=duration_ms,
            error_message=None if status == "success" else "boom",
        ),
    )


@pytest.mark.asyncio
async def test_summarize_by_tool_splits_success_and_error_counts(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    await _create_execution(db_session, conversation, org.id, user.id, "list_cubes", "success", 100)
    await _create_execution(db_session, conversation, org.id, user.id, "list_cubes", "success", 300)
    await _create_execution(db_session, conversation, org.id, user.id, "list_cubes", "error", 50)
    await _create_execution(db_session, conversation, org.id, user.id, "get_process", "success", 20)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    summary = await ai_tool_execution_repository.summarize_by_tool(db_session, org.id, since)

    by_tool = {entry["tool_name"]: entry for entry in summary}

    assert by_tool["list_cubes"]["total_calls"] == 3
    assert by_tool["list_cubes"]["success_count"] == 2
    assert by_tool["list_cubes"]["error_count"] == 1
    assert by_tool["list_cubes"]["avg_duration_ms"] == pytest.approx(150.0)

    assert by_tool["get_process"]["total_calls"] == 1
    assert by_tool["get_process"]["success_count"] == 1
    assert by_tool["get_process"]["error_count"] == 0


@pytest.mark.asyncio
async def test_summarize_by_tool_excludes_rows_before_since(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    old = await _create_execution(
        db_session, conversation, org.id, user.id, "list_cubes", "success", 100
    )
    now = datetime.now(timezone.utc)
    old.created_at = now - timedelta(days=40)
    await db_session.flush()

    since = now - timedelta(days=30)
    summary = await ai_tool_execution_repository.summarize_by_tool(db_session, org.id, since)

    assert summary == []
