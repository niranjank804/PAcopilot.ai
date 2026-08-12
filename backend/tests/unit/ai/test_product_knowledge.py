"""The assistant must be able to describe its own product, accurately.

Regression guard for a real defect: asked "what are Reports and Report
Workers?" — both visible in the navigation — the assistant had no
grounding, searched the knowledge base, found nothing (these are product
features, not customer documents) and gave up.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from src.ai.orchestrator import AIOrchestrator
from src.ai.product_knowledge import PRODUCT_OVERVIEW


@pytest.fixture
def orchestrator(monkeypatch):
    from src.ai import orchestrator as module

    # No database, no live connections — this is about prompt assembly.
    monkeypatch.setattr(
        module.tm1_integration_service,
        "list_connections",
        AsyncMock(return_value=[]),
    )

    return AIOrchestrator()


class TestPromptAssembly:

    @pytest.mark.asyncio
    async def test_product_knowledge_is_present_without_an_agent(
        self, orchestrator
    ):
        # The exact case from the bug report: general chat, no specialist
        # agent selected, so `persona` is None and the stable half would
        # otherwise be empty.
        stable, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system=None,
            persona=None,
        )

        assert stable is not None
        assert "Reports / Report Workers / Executions" in stable
        assert "report worker" in stable.lower()

    @pytest.mark.asyncio
    async def test_product_knowledge_is_in_the_stable_half(self, orchestrator):
        # Prompt caching is a byte-exact prefix match. This block never
        # varies per request, so it must not land in the volatile half —
        # that would invalidate the cache on every single call.
        stable, volatile = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system="retrieved knowledge excerpt",
            persona=None,
        )

        assert PRODUCT_OVERVIEW in stable
        assert PRODUCT_OVERVIEW not in (volatile or "")

    @pytest.mark.asyncio
    async def test_stable_half_is_byte_identical_across_requests(
        self, orchestrator
    ):
        first, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system="question one",
            persona=None,
        )
        second, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            # A different organization must not change the stable half.
            organization_id=uuid.uuid4(),
            system="a completely different question",
            persona=None,
        )

        assert first == second


class TestAccuracy:
    """A confident wrong answer about our own product reads as a bug."""

    def test_report_automation_is_labelled_as_preview(self):
        assert "DEVELOPER PREVIEW" in PRODUCT_OVERVIEW

    def test_unbuilt_features_are_explicitly_disclaimed(self):
        # Each of these is genuinely not implemented. Without naming them
        # the model fills the gap from what a reporting product usually
        # does — and confidently describes a scheduler we do not have.
        lowered = PRODUCT_OVERVIEW.lower()

        assert "no recurring scheduler" in lowered
        assert "no email delivery" in lowered
        assert "no ai-generated report" in lowered
        assert "no native tm1 report engine" in lowered

    def test_the_governance_boundary_is_stated(self):
        lowered = PRODUCT_OVERVIEW.lower()

        # The assistant explains; it does not act. Enforced by the
        # absence of tools, but stating it stops the model offering.
        assert "cannot create reports" in lowered
        assert 'press "run now"' in lowered or 'presses "run now"' in lowered

    def test_permissions_are_named_correctly(self):
        # These must match scripts/seed_permissions.py, or the assistant
        # sends users to ask for a permission that does not exist.
        assert "reports.execute" in PRODUCT_OVERVIEW
        assert "workers.manage" in PRODUCT_OVERVIEW

    def test_the_worker_is_described_as_outbound_and_customer_operated(self):
        lowered = PRODUCT_OVERVIEW.lower()

        # The single most misunderstood part of the architecture.
        assert "outbound" in lowered
        assert "windows" in lowered

    def test_permissions_named_here_exist_in_the_seed(self):
        from pathlib import Path

        seed = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "seed_permissions.py"
        ).read_text(encoding="utf-8")

        # Matched as a quoted literal rather than as `("code"` — the seed
        # list wraps long entries across lines, so the opening paren is
        # not reliably adjacent.
        for code in ("reports.execute", "workers.manage"):
            assert f'"{code}"' in seed, f"{code} is not seeded"

    def test_block_stays_compact(self):
        # Prepended to every request on every agent. Cached, but still
        # tokens not available for the user's actual problem.
        assert len(PRODUCT_OVERVIEW) < 3000
