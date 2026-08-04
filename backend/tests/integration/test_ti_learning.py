"""End-to-end test of the TI learning loop against a real database session."""

import json
import uuid

import pytest

from src.ai.tools.tm1.standards import GetCodingStandardsTool
from src.database.models.organization import Organization
from src.tm1.ti.learning import get_conventions, learn_from_processes

CLEAN = """601,100
602,"DATA - Load - {n}"
562,"NULL"
572,4

# =====================================
# PURPOSE : Load {n}
# =====================================
If( pMonth @= '' );
575,1
SaveDataAll;
"""

DIRTY = """601,100
602,"loader{n}"
562,"NULL"
572,2
nX = 1; # inline comment
CellPutN( nX, 'Finance', 'a' );
"""


@pytest.fixture
async def organization(db_session):
    org = Organization(
        id=uuid.uuid4(),
        name=f"Learning Test {uuid.uuid4().hex[:8]}",
        code=f"learn-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()
    return org


def corpus(clean: int, dirty: int) -> dict[str, str]:
    files = {
        f"DATA - Load - {i}pro.txt": CLEAN.format(n=i) for i in range(clean)
    }
    files.update(
        {f"loader{i}pro.txt": DIRTY.format(n=i) for i in range(dirty)}
    )
    return files


@pytest.mark.asyncio
async def test_learns_and_persists_conventions(db_session, organization):
    result = await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(12, 1)
    )

    assert result.parsed == 13
    assert result.failed == []
    assert result.stored_conventions > 0

    stored = await get_conventions(db_session, organization_id=organization.id)
    keys = {c.convention_key for c in stored}

    assert "no_inline_comments" in keys

    rule = next(c for c in stored if c.convention_key == "no_inline_comments")
    assert rule.support == 12
    assert rule.sample == 13
    assert rule.counter_examples == ["loader0"]


@pytest.mark.asyncio
async def test_relearning_replaces_rather_than_accumulates(
    db_session, organization
):
    """A second upload must not let the old corpus keep voting."""

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(20, 0)
    )
    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(9, 0)
    )

    stored = await get_conventions(db_session, organization_id=organization.id)
    rule = next(c for c in stored if c.convention_key == "no_inline_comments")

    assert rule.sample == 9


@pytest.mark.asyncio
async def test_small_unanimous_corpus_does_not_become_a_house_rule(
    db_session, organization
):
    """Damping: six files agreeing is not yet evidence of a convention."""

    result = await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(6, 0)
    )

    assert result.parsed == 6
    assert result.stored_conventions == 0


@pytest.mark.asyncio
async def test_weak_conventions_are_not_stored(db_session, organization):
    """Half the corpus disagreeing is not a house style."""

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(6, 6)
    )

    stored = await get_conventions(db_session, organization_id=organization.id)

    assert "no_inline_comments" not in {c.convention_key for c in stored}


@pytest.mark.asyncio
async def test_one_bad_file_does_not_lose_the_batch(db_session, organization):
    files = corpus(8, 0)
    files["broken.pro"] = "\x00 not a pro file at all"

    result = await learn_from_processes(
        db_session, organization_id=organization.id, files=files
    )

    assert result.parsed == 9
    assert result.stored_conventions > 0


@pytest.mark.asyncio
async def test_tool_reports_honestly_when_nothing_learned(
    db_session, organization, monkeypatch
):
    async def allow(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "src.ai.tools.tm1.standards.auth_repository.user_has_permission", allow
    )

    payload = json.loads(
        await GetCodingStandardsTool().execute(
            db_session,
            organization_id=organization.id,
            user_id=uuid.uuid4(),
        )
    )

    assert payload["conventions"] == []
    assert "no coding conventions" in payload["note"].lower()


@pytest.mark.asyncio
async def test_tool_returns_learned_conventions_with_evidence(
    db_session, organization, monkeypatch
):
    async def allow(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "src.ai.tools.tm1.standards.auth_repository.user_has_permission", allow
    )

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(12, 1)
    )

    payload = json.loads(
        await GetCodingStandardsTool().execute(
            db_session,
            organization_id=organization.id,
            user_id=uuid.uuid4(),
        )
    )

    rule = next(
        c for c in payload["conventions"] if c["key"] == "no_inline_comments"
    )

    assert rule["evidence"] == "12 of 13 analysed processes"
    assert rule["confidence"] >= 0.6


@pytest.mark.asyncio
async def test_conventions_are_scoped_to_one_organization(
    db_session, organization
):
    other = Organization(
        id=uuid.uuid4(),
        name=f"Other {uuid.uuid4().hex[:8]}",
        code=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    await db_session.flush()

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(12, 0)
    )

    assert await get_conventions(db_session, organization_id=other.id) == []


@pytest.mark.asyncio
async def test_parsed_processes_and_patterns_are_persisted(
    db_session, organization
):
    """Both were computed on every run and thrown away."""

    from sqlalchemy import select

    from src.database.models.tm1_process import TM1Process, TM1ProcessPattern

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(12, 0)
    )

    processes = (
        await db_session.execute(
            select(TM1Process).where(
                TM1Process.organization_id == organization.id
            )
        )
    ).scalars().all()

    assert len(processes) == 12
    assert all(p.name for p in processes)
    # Source code is deliberately not stored.
    assert not hasattr(processes[0], "prolog")

    patterns = (
        await db_session.execute(
            select(TM1ProcessPattern).where(
                TM1ProcessPattern.organization_id == organization.id
            )
        )
    ).scalars().all()

    assert all(p.evidence for p in patterns)


@pytest.mark.asyncio
async def test_relearning_replaces_stored_processes(db_session, organization):
    from sqlalchemy import func, select

    from src.database.models.tm1_process import TM1Process

    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(20, 0)
    )
    await learn_from_processes(
        db_session, organization_id=organization.id, files=corpus(9, 0)
    )

    count = await db_session.scalar(
        select(func.count())
        .select_from(TM1Process)
        .where(TM1Process.organization_id == organization.id)
    )

    assert count == 9


@pytest.mark.asyncio
async def test_duplicate_process_names_do_not_fail_the_upload(
    db_session, organization
):
    """Two folders merged, or a re-download, can repeat a name."""

    files = corpus(10, 0)
    files["copy of DATA - Load - 0pro.txt"] = files["DATA - Load - 0pro.txt"]

    result = await learn_from_processes(
        db_session, organization_id=organization.id, files=files
    )

    assert result.parsed == 11
