"""Capability registry consistency + prompt-cache regression.

Regression guard for a real defect: asked "what are Reports and Report
Workers?" — both visible in the navigation — the assistant had no
grounding, searched the knowledge base, found nothing, and gave up.

The deeper guard is against the *next* version of that bug: prose that
drifts out of step with what the product actually does. The capability
section is generated from the registry, and these tests keep the registry
honest.
"""

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.ai.capabilities import (
    CAPABILITIES,
    CAPABILITIES_BY_KEY,
    USABLE_STATUSES,
    Capability,
    CapabilityStatus,
    by_status,
    is_usable,
)
from src.ai.orchestrator import AIOrchestrator
from src.ai.product_knowledge import PRODUCT_OVERVIEW

# backend/tests/unit/ai/<this file> -> parents[3] is backend/, [4] is the
# repository root. Registry paths are repo-relative.
REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def orchestrator(monkeypatch):
    from src.ai import orchestrator as module

    monkeypatch.setattr(
        module.tm1_integration_service,
        "list_connections",
        AsyncMock(return_value=[]),
    )

    return AIOrchestrator()


# ======================================================================
# TEST A — every AVAILABLE / PREVIEW capability has real code behind it
# ======================================================================


class TestAImplementationReferences:

    @pytest.mark.parametrize(
        "capability",
        [c for c in CAPABILITIES if c.status in USABLE_STATUSES],
        ids=lambda c: c.key,
    )
    def test_usable_capability_names_an_implementation(
        self, capability: Capability
    ):
        assert capability.implementation, (
            f"{capability.key} is {capability.status.value} but names no "
            "implementation"
        )

    @pytest.mark.parametrize(
        "capability",
        [c for c in CAPABILITIES if c.status in USABLE_STATUSES],
        ids=lambda c: c.key,
    )
    def test_the_implementation_actually_exists(self, capability: Capability):
        # The point of the whole registry: a capability cannot be claimed
        # shippable while pointing at code that was never written, or was
        # deleted in a later refactor.
        path = REPO_ROOT / capability.implementation

        assert path.exists(), (
            f"{capability.key} points at {capability.implementation}, which "
            "does not exist"
        )

    @pytest.mark.parametrize(
        "capability",
        [c for c in CAPABILITIES if c.status is CapabilityStatus.PLANNED],
        ids=lambda c: c.key,
    )
    def test_planned_capability_claims_no_implementation(
        self, capability: Capability
    ):
        # A PLANNED entry with an implementation path is a contradiction:
        # either it is built (and mis-labelled) or the path is wrong.
        assert capability.implementation is None
        assert capability.permission is None


# ======================================================================
# TEST B — PLANNED is never described as usable
# ======================================================================


class TestBPlannedIsNeverUsable:

    def test_planned_capabilities_are_under_the_unavailable_heading(self):
        heading = "NOT CURRENTLY AVAILABLE"

        assert heading in PRODUCT_OVERVIEW

        tail = PRODUCT_OVERVIEW.split(heading, 1)[1]

        for capability in by_status(CapabilityStatus.PLANNED):
            assert capability.name in tail, (
                f"{capability.key} is PLANNED but does not appear under "
                f"'{heading}'"
            )

    def test_planned_capabilities_are_not_in_the_available_section(self):
        available_block = PRODUCT_OVERVIEW.split(
            "AVAILABLE (these work today):", 1
        )[1].split("DEVELOPER PREVIEW", 1)[0]

        for capability in by_status(CapabilityStatus.PLANNED):
            assert capability.name not in available_block

    def test_the_prompt_instructs_against_describing_them_as_working(self):
        assert "do NOT work" in PRODUCT_OVERVIEW
        assert "Never describe anything under NOT CURRENTLY AVAILABLE" in (
            PRODUCT_OVERVIEW
        )

    def test_is_usable_rejects_planned(self):
        for capability in by_status(CapabilityStatus.PLANNED):
            assert not is_usable(capability.key)

    @pytest.mark.parametrize(
        "key",
        [
            "report_scheduling",
            "email_delivery",
            "ai_report_drafting",
            "native_tm1_reporting",
            "report_bursting",
            "stet_schedule_approval",
        ],
    )
    def test_the_specific_unbuilt_features_are_registered_as_planned(self, key):
        # Named explicitly: these are the ones a model will otherwise
        # invent, because reporting products normally have them.
        assert CAPABILITIES_BY_KEY[key].status is CapabilityStatus.PLANNED


# ======================================================================
# TEST C — DEVELOPER_PREVIEW always carries preview language
# ======================================================================


class TestCPreviewLanguage:

    @pytest.mark.parametrize(
        "capability",
        by_status(CapabilityStatus.DEVELOPER_PREVIEW),
        ids=lambda c: c.key,
    )
    def test_each_preview_capability_is_marked_in_the_prompt(
        self, capability: Capability
    ):
        # Find the rendered line for this capability and check it carries
        # the marker, rather than checking the document merely contains
        # the phrase somewhere.
        line = next(
            (
                candidate
                for candidate in PRODUCT_OVERVIEW.splitlines()
                if candidate.startswith(f"- {capability.name}:")
            ),
            None,
        )

        assert line is not None, f"{capability.key} not rendered"
        assert "DEVELOPER PREVIEW" in line

    def test_report_execution_carries_the_pafe_caveat(self):
        # The single most important caveat in the product right now.
        assert "NOT yet been validated against a real Planning Analytics" in (
            PRODUCT_OVERVIEW
        )

    def test_the_session_zero_finding_is_preserved(self):
        # Discovered in Phase 1; must not be lost as the prompt evolves.
        assert "Session 0" in PRODUCT_OVERVIEW


# ======================================================================
# TEST D — no invented permissions
# ======================================================================


class TestDPermissionsExist:

    @staticmethod
    def _seeded_permissions() -> set[str]:
        seed = (
            REPO_ROOT / "backend" / "scripts" / "seed_permissions.py"
        ).read_text(encoding="utf-8")

        # Codes have two or three dotted segments (tm1.read,
        # pa.connections.read), so the pattern must allow both — a
        # two-segment-only pattern silently drops pa.* codes and then
        # reports them as unseeded.
        return set(re.findall(r'"([a-z0-9_]+(?:\.[a-z0-9_]+)+)"', seed))

    @pytest.mark.parametrize(
        "capability",
        [c for c in CAPABILITIES if c.permission],
        ids=lambda c: c.key,
    )
    def test_registry_permissions_are_seeded(self, capability: Capability):
        # Telling a user to request a permission that does not exist
        # sends them to an administrator who cannot grant it.
        assert capability.permission in self._seeded_permissions(), (
            f"{capability.key} requires '{capability.permission}', which is "
            "not in seed_permissions.py"
        )

    def test_every_permission_named_in_the_prompt_is_seeded(self):
        seeded = self._seeded_permissions()

        mentioned = set(
            re.findall(
                r"the ([a-z0-9_]+(?:\.[a-z0-9_]+)+) permission", PRODUCT_OVERVIEW
            )
        )

        assert mentioned, "no permissions mentioned — the check would be vacuous"
        assert mentioned <= seeded, f"unseeded: {sorted(mentioned - seeded)}"


# ======================================================================
# TEST E — the assistant claims no authority to act
# ======================================================================


class TestENoUnauthorizedActionClaims:

    def test_the_prompt_disclaims_the_ability_to_act(self):
        lowered = PRODUCT_OVERVIEW.lower()

        assert "cannot create reports" in lowered
        assert "start executions" in lowered
        assert "register workers" in lowered
        assert "no tool for those" in lowered

    def test_it_states_actions_are_permission_gated(self):
        assert "gated by permissions" in PRODUCT_OVERVIEW

    def test_no_report_or_worker_mutation_tool_is_registered(self):
        # The real enforcement is the absence of tools; this asserts the
        # prompt is not lying about that, and would fail loudly if a
        # future phase wired one up without revisiting the text.
        from src.ai.tools.registry import TOOLS

        forbidden = re.compile(
            r"(create|run|execute|start|schedule|send|register|delete)_"
            r".*(report|worker|schedule|artifact)"
        )

        offenders = [name for name in TOOLS if forbidden.search(name)]

        assert not offenders, (
            f"tools {offenders} can act on report automation, but the "
            "product knowledge tells users the assistant cannot"
        )

    def test_cross_capability_inference_is_explicitly_blocked(self):
        # The red-team case: "your worker is online, so email this".
        assert "does not mean reports can be emailed" in PRODUCT_OVERVIEW
        assert "does not mean schedules can be created" in PRODUCT_OVERVIEW


# ======================================================================
# TEST F — prompt caching: the stable prefix never varies
# ======================================================================


class TestFPromptCacheStability:

    @pytest.mark.asyncio
    async def test_stable_half_is_identical_across_tenants_and_questions(
        self, orchestrator
    ):
        first, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system="a question from one organization",
            persona=None,
        )
        second, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system="a completely different question from another",
            persona=None,
        )

        # Byte-exact: prompt caching is a prefix match, so any variance
        # here is a permanent cache miss on every request.
        assert first == second

    @pytest.mark.asyncio
    async def test_product_knowledge_is_in_the_stable_half_only(
        self, orchestrator
    ):
        stable, volatile = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system="retrieved knowledge excerpt",
            persona=None,
        )

        assert PRODUCT_OVERVIEW in stable
        assert PRODUCT_OVERVIEW not in (volatile or "")

    @pytest.mark.asyncio
    async def test_present_even_with_no_specialist_agent(self, orchestrator):
        # The exact reported case: general chat, persona is None, and the
        # stable half would otherwise be empty.
        stable, _ = await orchestrator._build_tool_system_prompt(
            db=None,
            organization_id=uuid.uuid4(),
            system=None,
            persona=None,
        )

        assert stable is not None
        assert "Report workers" in stable

    def test_the_block_contains_no_volatile_data(self):
        # Nothing organization-, user- or connection-specific may leak
        # into the cached prefix.
        for forbidden in ("organization_id", "connection_id", "user_id", "http"):
            assert forbidden not in PRODUCT_OVERVIEW.lower(), forbidden

    def test_generation_is_deterministic(self):
        from src.ai.product_knowledge import _build_overview

        assert _build_overview() == _build_overview() == PRODUCT_OVERVIEW


# ======================================================================
# Registry hygiene
# ======================================================================


class TestRegistryHygiene:

    def test_keys_are_unique(self):
        keys = [capability.key for capability in CAPABILITIES]

        assert len(keys) == len(set(keys))

    def test_every_capability_is_rendered(self):
        for capability in CAPABILITIES:
            assert capability.name in PRODUCT_OVERVIEW, capability.key

    def test_block_stays_within_a_sane_token_budget(self):
        # Prepended to every request on every agent. Cached, but still
        # tokens not available for the user's actual problem.
        assert len(PRODUCT_OVERVIEW) < 6000

    def test_no_capability_is_left_unclassified(self):
        for capability in CAPABILITIES:
            assert capability.status in CapabilityStatus
