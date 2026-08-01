"""The quota is what makes plans mean anything commercially, so it is tested
against the orchestrator's real code path rather than the catalog alone."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.core.exceptions import QuotaExceededException


def _org(plan):
    organization = MagicMock()
    organization.plan = plan
    return organization


async def _check(plan, tokens_used, deployment_limit=None):
    original = settings.AI_MONTHLY_TOKEN_LIMIT
    settings.AI_MONTHLY_TOKEN_LIMIT = deployment_limit
    try:
        with patch(
            "src.ai.orchestrator.organization_repository.get_by_id",
            new=AsyncMock(return_value=_org(plan)),
        ), patch(
            "src.ai.orchestrator.ai_usage_repository.get_total_tokens_since",
            new=AsyncMock(return_value=tokens_used),
        ):
            await ai_orchestrator._check_usage_quota(None, uuid.uuid4())
    finally:
        settings.AI_MONTHLY_TOKEN_LIMIT = original


@pytest.mark.asyncio
class TestPlanQuota:

    async def test_under_trial_limit_allowed(self):
        await _check("trial", tokens_used=1_999_999)

    async def test_at_trial_limit_blocked(self):
        with pytest.raises(QuotaExceededException):
            await _check("trial", tokens_used=2_000_000)

    async def test_professional_allows_what_trial_blocks(self):
        # Same usage, different plan — this is the commercial mechanism.
        with pytest.raises(QuotaExceededException):
            await _check("trial", tokens_used=3_000_000)

        await _check("professional", tokens_used=3_000_000)

    async def test_enterprise_unlimited_by_default(self):
        await _check("enterprise", tokens_used=10**12)

    async def test_deployment_limit_caps_unlimited_plan(self):
        with pytest.raises(QuotaExceededException):
            await _check("enterprise", tokens_used=500, deployment_limit=100)

    async def test_deployment_limit_also_caps_paid_plans(self):
        # The operator backstop binds everyone, or it is not a backstop.
        with pytest.raises(QuotaExceededException):
            await _check("professional", tokens_used=500, deployment_limit=100)

    async def test_generous_deployment_limit_leaves_plan_in_charge(self):
        with pytest.raises(QuotaExceededException):
            await _check(
                "trial", tokens_used=2_000_000, deployment_limit=50_000_000
            )

    async def test_unknown_plan_falls_back_to_default_limit(self):
        with pytest.raises(QuotaExceededException):
            await _check("legacy_gold", tokens_used=2_000_000)

    async def test_missing_organization_is_metered_not_unlimited(self):
        # An absent organization row means corrupted or deleted state. It must
        # resolve to the default plan's ceiling — granting uncapped AI spend to
        # something we cannot identify is the expensive failure.
        with pytest.raises(QuotaExceededException):
            await _check(None, tokens_used=10**9)

    async def test_missing_organization_still_allowed_under_default_limit(self):
        await _check(None, tokens_used=10)
