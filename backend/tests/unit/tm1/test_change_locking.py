"""Every status transition on a draft takes the row lock first.

Two executors that both read "draft" used to both write to TM1. The lock
makes the second wait for the first's transaction and then see
"executed". Postgres semantics cannot be exercised on one test
connection, so these tests pin the mechanism: the lock is taken, and
the state it returns is what the guard reads.
"""

import uuid

import pytest

from src.core.exceptions import ConflictException
from src.database.models.tm1_change import TM1Change
from src.repositories.tm1_change_repository import tm1_change_repository
from src.tm1.deployment.change_service import change_service


def _draft(status: str = "draft") -> TM1Change:
    return TM1Change(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        change_type="update_rules",
        target_name="Sales",
        new_content="[] = N: 1;",
        status=status,
    )


@pytest.fixture
def locked_state(monkeypatch):
    """Stand in for the database: `lock_for_update` returns whatever the
    committed row says, however stale the caller's copy is."""

    calls: list[uuid.UUID] = []
    state: dict = {"row": None}

    async def fake_lock(db, change_id):
        calls.append(change_id)
        return state["row"]

    monkeypatch.setattr(tm1_change_repository, "lock_for_update", fake_lock)

    return calls, state


@pytest.mark.asyncio
async def test_execute_reads_the_status_from_the_locked_row(locked_state):
    calls, state = locked_state
    stale = _draft("draft")
    # What the other executor committed a moment ago.
    state["row"] = _draft("executed")
    state["row"].id = stale.id

    with pytest.raises(ConflictException, match="executed"):
        await change_service.execute_change(None, stale, uuid.uuid4())

    assert calls == [stale.id]


@pytest.mark.asyncio
async def test_reject_and_rollback_take_the_same_lock(locked_state):
    calls, state = locked_state

    state["row"] = _draft("executed")
    with pytest.raises(ConflictException):
        await change_service.reject_change(None, state["row"])

    state["row"] = _draft("draft")
    with pytest.raises(ConflictException):
        await change_service.rollback_change(None, state["row"])

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_the_repository_lock_is_a_select_for_update(monkeypatch):
    """The statement itself — the part the fake above stands in for."""

    captured: dict = {}

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        async def execute(self, statement):
            captured["sql"] = str(statement.compile(compile_kwargs={"literal_binds": False}))
            captured["options"] = statement.get_execution_options()
            return FakeResult()

    await tm1_change_repository.lock_for_update(FakeSession(), uuid.uuid4())

    assert "FOR UPDATE" in captured["sql"]
    assert captured["options"].get("populate_existing") is True


@pytest.mark.asyncio
async def test_lock_keeps_the_callers_row_when_nothing_is_found(monkeypatch):
    """A draft deleted underneath the caller: the guard then reports the
    caller's own state rather than failing on None."""

    async def fake_lock(db, change_id):
        return None

    monkeypatch.setattr(tm1_change_repository, "lock_for_update", fake_lock)
    change = _draft()

    assert await change_service._lock(None, change) is change
