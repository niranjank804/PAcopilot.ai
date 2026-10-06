import os

import pytest
from sqlalchemy import select

from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.database.models.ai_tool_execution import AIToolExecution
from tests.fixtures.factories import grant_system_role


pytestmark = pytest.mark.live_ai


@pytest.fixture
def require_anthropic_key():
    # A paid model call: only on the explicit opt-in, never because a key
    # happens to be present in the environment.
    if os.environ.get("LIVE_AI") != "1":
        pytest.skip("LIVE_AI=1 not set — paid AI calls not authorized for this run")
    if not settings.ANTHROPIC_API_KEY:
        pytest.skip(
            "ANTHROPIC_API_KEY not set — skipping real AI + TM1 tool-call test "
            "(independent of the TM1_* variables; both are needed for this file)."
        )


@pytest.mark.asyncio
async def test_developer_agent_lists_real_cubes_via_tool_call(
    db_session, live_connection, require_anthropic_key
):
    org, user, connection = live_connection
    # Reading TM1 needs tm1.read; a user with no role is refused, as it should be.
    await grant_system_role(db_session, user.id, "Organization Admin")

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message=(
            f"Using TM1 connection {connection.id}, list the cubes available "
            "in this model. Use the list_cubes tool to find out — don't guess."
        ),
        agent="developer",
    )

    assert result.content

    executions = (
        (
            await db_session.execute(
                select(AIToolExecution).where(
                    AIToolExecution.conversation_id == result.conversation_id
                )
            )
        )
        .scalars()
        .all()
    )

    assert any(
        execution.tool_name == "list_cubes" and execution.status == "success"
        for execution in executions
    ), (
        "Expected the developer agent to call list_cubes successfully at "
        f"least once; tool executions recorded: "
        f"{[(e.tool_name, e.status) for e in executions]}"
    )
