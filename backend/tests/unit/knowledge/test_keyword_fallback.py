"""The keyword fallback's contract, minus the database.

The integration tests prove full-text search actually finds a passage.
These pin the parts that are easy to get quietly wrong: that the mode
survives an empty result, that the two score scales are never compared,
and that a degraded search is reported to the *agent* and not only to
the UI.
"""

import json
import uuid

import pytest

from src.knowledge import retrieval
from src.knowledge.retrieval import KEYWORD, SEMANTIC, SearchOutcome


class TestSearchOutcome:

    def test_it_is_a_list(self):
        """Six call sites, including an AI tool, treat this as a list."""

        outcome = SearchOutcome([1, 2, 3], mode=SEMANTIC)

        assert isinstance(outcome, list)
        assert list(outcome) == [1, 2, 3]
        assert len(outcome) == 3

    def test_an_empty_result_still_carries_its_mode(self):
        """The case the mode exists for.

        When embeddings are down *and* keyword search finds nothing, the
        answer must still be able to say the search was degraded. Reading
        the mode off `matches[0]` — the obvious shortcut — reports a
        confident "semantic" for exactly this situation.
        """

        outcome = SearchOutcome([], mode=KEYWORD)

        assert not outcome
        assert outcome.mode == KEYWORD

    def test_it_defaults_to_semantic(self):
        """So the embedding path reads unchanged."""

        assert SearchOutcome([]).mode == SEMANTIC


class TestScoreScalesAreNotConflated:

    def test_the_two_floors_are_different_constants(self):
        """`ts_rank` is not a cosine similarity.

        Applying the 0.2 cosine floor to ts_rank would discard nearly
        every genuine keyword match, since ts_rank for a short document
        is routinely far below it.
        """

        assert retrieval.MINIMUM_SCORE == 0.2
        assert retrieval.KEYWORD_MINIMUM_SCORE < retrieval.MINIMUM_SCORE

    def test_a_realistic_ts_rank_would_be_dropped_by_the_cosine_floor(self):
        """Demonstrates why the separate floor is needed, not just tidy.

        0.0607 is what Postgres returns for a single-term match on a
        short chunk — well below the cosine floor, and a perfectly good
        keyword hit.
        """

        realistic_ts_rank = 0.0607

        assert realistic_ts_rank < retrieval.MINIMUM_SCORE
        assert realistic_ts_rank >= retrieval.KEYWORD_MINIMUM_SCORE


class TestTheAgentIsToldWhenRetrievalIsDegraded:
    """The tool answers "what are our standards?" for a model about to
    draft production TurboIntegrator. Silently handing it keyword matches
    invites a confident false negative."""

    @pytest.fixture
    def tool(self):
        from src.ai.tools.knowledge import SearchKnowledgeBaseTool

        return SearchKnowledgeBaseTool()

    async def _run(self, tool, monkeypatch, outcome):
        from src.knowledge.service import knowledge_service
        from src.repositories.auth_repository import auth_repository

        async def allow(*args, **kwargs):
            return True

        async def fake_search(*args, **kwargs):
            return outcome

        monkeypatch.setattr(auth_repository, "user_has_permission", allow)
        monkeypatch.setattr(knowledge_service, "search", fake_search)

        return json.loads(
            await tool.execute(
                None,
                organization_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                query="TI process naming convention",
            )
        )

    @pytest.mark.asyncio
    async def test_a_degraded_empty_result_says_so(self, tool, monkeypatch):
        """"Nothing found" and "nothing found by word search" call for
        different behaviour from the agent."""

        payload = await self._run(
            tool, monkeypatch, SearchOutcome([], mode=KEYWORD)
        )

        assert payload["results"] == []
        assert "semantic search is currently unavailable" in payload["note"]

    @pytest.mark.asyncio
    async def test_a_normal_empty_result_does_not_claim_an_outage(
        self, tool, monkeypatch
    ):
        payload = await self._run(
            tool, monkeypatch, SearchOutcome([], mode=SEMANTIC)
        )

        assert "unavailable" not in payload["note"]

    @pytest.mark.asyncio
    async def test_degraded_hits_are_flagged_as_incomplete(
        self, tool, monkeypatch
    ):
        """The dangerous case: results came back, so nothing looks wrong."""

        class FakeDocument:
            filename = "standards.pro"

        class FakeChunk:
            document = FakeDocument()
            chunk_index = 0
            content = "prolog naming convention"

        class FakeMatch:
            chunk = FakeChunk()
            score = 0.06

        payload = await self._run(
            tool, monkeypatch, SearchOutcome([FakeMatch()], mode=KEYWORD)
        )

        assert len(payload["results"]) == 1
        assert "keyword search" in payload["note"]
        assert "incomplete" in payload["note"]

    @pytest.mark.asyncio
    async def test_semantic_hits_carry_no_caveat(self, tool, monkeypatch):
        """A caveat on every answer is a caveat nobody reads."""

        class FakeDocument:
            filename = "standards.pro"

        class FakeChunk:
            document = FakeDocument()
            chunk_index = 0
            content = "prolog naming convention"

        class FakeMatch:
            chunk = FakeChunk()
            score = 0.91

        payload = await self._run(
            tool, monkeypatch, SearchOutcome([FakeMatch()], mode=SEMANTIC)
        )

        assert payload["results"]
        assert "note" not in payload
