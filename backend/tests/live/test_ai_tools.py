import pytest
from sqlalchemy import select

from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.database.models.ai_tool_execution import AIToolExecution


@pytest.fixture
def require_anthropic_key():
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
