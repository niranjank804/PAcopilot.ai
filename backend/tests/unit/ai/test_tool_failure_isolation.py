"""A failing tool must not take the conversation turn with it.

Before this, `_execute_tool_call` caught only `AppException`. Anything
else propagated and the user got a 500 instead of an answer.

The common trigger is not exotic: 18 of 24 tools parse a model-supplied
`connection_id` with `uuid.UUID()`, so a model passing a connection
*name* ("pa trial") rather than its id raises `ValueError`. That is a
mistake the model can correct by itself — given the chance.
"""

import inspect
import uuid

import pytest

from src.ai.orchestrator import AIOrchestrator
from src.ai.schemas import ToolCall
from src.ai.tools.registry import TOOLS
from src.core.exceptions import AppException, NotFoundException


class Exploding:
    """A registered tool that raises a non-AppException."""

    name = "exploding_tool"
    description = "raises"
    input_schema: dict = {"type": "object", "properties": {}}
    required_permission = None

    def __init__(self, exception):
        self._exception = exception

    async def execute(self, db, **kwargs):
        raise self._exception


@pytest.fixture
def orchestrator():
    return AIOrchestrator()


@pytest.fixture
def recorded(monkeypatch):
    """Capture tool-execution rows without touching the database."""

    rows = []

    async def fake_record(self, db, **kwargs):
        rows.append(kwargs)

    monkeypatch.setattr(
        AIOrchestrator, "_record_tool_execution", fake_record
    )

    return rows


async def _call(orchestrator, monkeypatch, exception):
    tool = Exploding(exception)
    monkeypatch.setattr(
        "src.ai.orchestrator.get_tool", lambda name: tool
    )

    return await orchestrator._execute_tool_call(
        None,
        ToolCall(id="tc-1", name="exploding_tool", input={}),
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )


class TestTheTurnSurvives:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception",
        [
            # The realistic one: a model passing a connection name.
            ValueError("badly formed hexadecimal UUID string"),
            KeyError("connection_id"),
            TypeError("unexpected keyword argument"),
            RuntimeError("something unforeseen"),
            AttributeError("'NoneType' object has no attribute 'x'"),
        ],
        ids=lambda e: type(e).__name__,
    )
    async def test_a_non_app_exception_is_contained(
        self, orchestrator, monkeypatch, recorded, exception
    ):
        result = await _call(orchestrator, monkeypatch, exception)

        # Returned as a tool error rather than raised.
        assert result.is_error is True
        assert result.tool_call_id == "tc-1"

    @pytest.mark.asyncio
    async def test_the_model_is_told_how_to_correct_itself(
        self, orchestrator, monkeypatch, recorded
    ):
        result = await _call(
            orchestrator, monkeypatch, ValueError("bad uuid")
        )

        # Actionable, not "an error occurred": the model needs to know
        # connection_id is a UUID from the system context, not a name.
        assert "connection_id" in result.content
        assert "UUID" in result.content or "uuid" in result.content.lower()

    @pytest.mark.asyncio
    async def test_the_failure_is_recorded_for_monitoring(
        self, orchestrator, monkeypatch, recorded
    ):
        await _call(orchestrator, monkeypatch, ValueError("bad uuid"))

        assert len(recorded) == 1
        assert recorded[0]["status"] == "error"
        assert recorded[0]["tool_name"] == "exploding_tool"

    @pytest.mark.asyncio
    async def test_the_recorded_message_leaks_no_detail(
        self, orchestrator, monkeypatch, recorded
    ):
        """This row is shown in the monitoring UI.

        An arbitrary exception message can carry a connection string, a
        file path or a TM1 credential, so only the type name is stored.
        """

        secret = "postgresql://user:hunter2@db.internal:5432/prod"

        await _call(orchestrator, monkeypatch, RuntimeError(secret))

        message = recorded[0]["error_message"]

        assert message == "RuntimeError"
        assert "hunter2" not in message
        assert "db.internal" not in message


class TestExistingBehaviourPreserved:

    @pytest.mark.asyncio
    async def test_not_found_is_still_classified_separately(
        self, orchestrator, monkeypatch, recorded
    ):
        """The expected-negative distinction must survive.

        Counting "this object doesn't exist" as an error is what makes a
        read tool sit at a permanently high error rate.
        """

        await _call(
            orchestrator, monkeypatch, NotFoundException("no such process")
        )

        assert recorded[0]["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_an_app_exception_still_returns_its_own_message(
        self, orchestrator, monkeypatch, recorded
    ):
        # AppException messages are ours and safe to show the model.
        await _call(
            orchestrator, monkeypatch, AppException("a deliberate message")
        )

        assert recorded[0]["status"] == "error"
        assert recorded[0]["error_message"] == "a deliberate message"


class TestExposureScope:

    def test_most_tools_parse_a_model_supplied_uuid(self):
        """Documents why the safety net matters.

        If this ratio ever drops to zero the tools stopped taking raw
        UUIDs from the model, and the net is less critical — but it
        should still exist.
        """

        parsing = [
            name
            for name, tool in TOOLS.items()
            if "uuid.UUID(str(kwargs" in inspect.getsource(type(tool))
        ]

        assert len(parsing) > 10, (
            "expected many tools to parse a model-supplied connection_id"
        )

    def test_a_bad_uuid_really_is_not_an_app_exception(self):
        # The premise of the whole fix.
        with pytest.raises(ValueError) as exc_info:
            uuid.UUID("pa trial")

        assert not isinstance(exc_info.value, AppException)
