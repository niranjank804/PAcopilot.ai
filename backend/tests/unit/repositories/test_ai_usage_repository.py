from datetime import datetime, timedelta, timezone

import pytest

from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_usage_repository import ai_usage_repository
from tests.fixtures.factories import create_organization, create_user


async def _create_conversation(db_session, organization_id, user_id):
    return await ai_conversation_repository.create(
        db_session,
        AIConversation(organization_id=organization_id, user_id=user_id),
    )


async def _create_usage(
    db_session,
    conversation,
    organization_id,
    user_id,
    model,
    total_tokens,
    cost,
):
    return await ai_usage_repository.create(
        db_session,
        AIUsage(
            conversation_id=conversation.id,
            organization_id=organization_id,
            user_id=user_id,
            provider="anthropic",
            model=model,
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - total_tokens // 2,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
            latency_ms=100,
        ),
    )


@pytest.mark.asyncio
async def test_get_total_tokens_since_sums_only_recent_rows(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    now = datetime.now(timezone.utc)

    await _create_usage(db_session, conversation, org.id, user.id, "claude-opus-4-8", 100, 1.5)

    old = await _create_usage(
        db_session, conversation, org.id, user.id, "claude-opus-4-8", 500, 5.0
    )
    old.created_at = now - timedelta(days=40)
    await db_session.flush()

    since = now - timedelta(days=30)
    total = await ai_usage_repository.get_total_tokens_since(db_session, org.id, since)

    assert total == 100


@pytest.mark.asyncio
async def test_get_total_tokens_since_returns_zero_when_no_usage(db_session):
    org = await create_organization(db_session)

    since = datetime.now(timezone.utc) - timedelta(days=30)
    total = await ai_usage_repository.get_total_tokens_since(db_session, org.id, since)

    assert total == 0


@pytest.mark.asyncio
async def test_summarize_returns_totals(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    await _create_usage(db_session, conversation, org.id, user.id, "claude-opus-4-8", 100, 1.5)
    await _create_usage(db_session, conversation, org.id, user.id, "claude-opus-4-8", 200, 2.5)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    summary = await ai_usage_repository.summarize(db_session, org.id, since)

    assert summary["total_requests"] == 2
    assert summary["total_tokens"] == 300
    assert float(summary["total_cost_usd"]) == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_summarize_by_model_groups_correctly(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    await _create_usage(db_session, conversation, org.id, user.id, "claude-opus-4-8", 100, 1.0)
    await _create_usage(db_session, conversation, org.id, user.id, "claude-opus-4-8", 100, 1.0)
    await _create_usage(db_session, conversation, org.id, user.id, "claude-haiku-4-5", 50, 0.1)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    by_model = await ai_usage_repository.summarize_by_model(db_session, org.id, since)

    by_model_map = {entry["model"]: entry for entry in by_model}

    assert by_model_map["claude-opus-4-8"]["requests"] == 2
    assert by_model_map["claude-opus-4-8"]["total_tokens"] == 200
    assert by_model_map["claude-haiku-4-5"]["requests"] == 1
    assert by_model_map["claude-haiku-4-5"]["total_tokens"] == 50
