import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.tm1.resilience import (
    CircuitState,
    get_circuit_breaker,
    remove_circuit_breaker,
)
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


@pytest.mark.asyncio
async def test_breaker_open_connections_are_pruned_from_tool_prompt(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    async def make_connection(name):
        return await tm1_integration_service.create_connection(
            db_session,
            organization_id=org.id,
            created_by=user.id,
            name=name,
            address=f"{name}.example.com",
            port=8010,
            ssl=True,
            username="admin",
            password="secret",
        )

    healthy = await make_connection("healthy")
    dead = await make_connection("dead")

    breaker = get_circuit_breaker(dead.id)
    breaker.state = CircuitState.OPEN

    try:
        prompt = await ai_orchestrator._build_tool_system_prompt(
            db_session, org.id, None, None
        )

        assert str(healthy.id) in prompt
        assert str(dead.id) not in prompt
    finally:
        remove_circuit_breaker(dead.id)
