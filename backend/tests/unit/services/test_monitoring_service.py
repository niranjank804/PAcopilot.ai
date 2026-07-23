from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_tool_execution import AIToolExecution
from src.database.models.ai_usage import AIUsage
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from src.repositories.ai_usage_repository import ai_usage_repository
from src.services.monitoring_service import monitoring_service
from src.tm1.resilience import get_circuit_breaker, remove_circuit_breaker
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


async def _create_conversation(db_session, organization_id, user_id):
    return await ai_conversation_repository.create(
        db_session,
        AIConversation(organization_id=organization_id, user_id=user_id),
    )


@pytest.mark.asyncio
async def test_get_usage_summary_totals_and_by_model(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    await ai_usage_repository.create(
        db_session,
        AIUsage(
            conversation_id=conversation.id,
            organization_id=org.id,
            user_id=user.id,
            provider="anthropic",
            model="claude-opus-4-8",
            prompt_tokens=50,
            completion_tokens=50,
            total_tokens=100,
            estimated_cost_usd=1.0,
            latency_ms=100,
        ),
    )

    summary = await monitoring_service.get_usage_summary(db_session, org.id, days=30)

    assert summary["total_requests"] == 1
    assert summary["total_tokens"] == 100
    assert summary["by_model"][0]["model"] == "claude-opus-4-8"


@pytest.mark.asyncio
async def test_get_tool_summary_reports_success_and_error(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    conversation = await _create_conversation(db_session, org.id, user.id)

    await ai_tool_execution_repository.create(
        db_session,
        AIToolExecution(
            conversation_id=conversation.id,
            organization_id=org.id,
            user_id=user.id,
            tool_name="list_cubes",
            arguments={},
            status="success",
            result_summary=None,
            duration_ms=42,
            error_message=None,
        ),
    )

    summary = await monitoring_service.get_tool_summary(db_session, org.id, days=30)

    assert summary[0]["tool_name"] == "list_cubes"
    assert summary[0]["success_count"] == 1
    assert summary[0]["error_count"] == 0


@pytest.mark.asyncio
async def test_get_tm1_status_reflects_circuit_breaker_state(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Prod",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )

    breaker = get_circuit_breaker(connection.id)
    breaker.record_failure()

    statuses = await monitoring_service.get_tm1_status(db_session, org.id)

    assert len(statuses) == 1
    assert statuses[0]["connection_id"] == connection.id
    assert statuses[0]["failure_count"] == 1

    remove_circuit_breaker(connection.id)


@pytest.mark.asyncio
async def test_get_tm1_status_defaults_to_closed_for_untouched_connection(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Prod",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )

    statuses = await monitoring_service.get_tm1_status(db_session, org.id)

    assert statuses[0]["state"] == "closed"
    assert statuses[0]["failure_count"] == 0
