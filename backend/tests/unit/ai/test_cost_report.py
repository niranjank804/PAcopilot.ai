"""AI cost report (phase 9): spend by agent and tier, savings, fallback rate."""

from decimal import Decimal

import pytest

from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
from src.services.monitoring_service import ai_cost_report
from tests.fixtures.factories import auth_headers, create_org_admin, create_organization


def _usage(org_id, user_id, conversation_id, *, model, tier, agent, reason, cost, fell_back=False,
           prompt=1000, completion=500, cache_read=0, latency=1200):
    return AIUsage(
        conversation_id=conversation_id, organization_id=org_id, user_id=user_id,
        provider="anthropic", model=model, prompt_tokens=prompt, completion_tokens=completion,
        total_tokens=prompt + completion + cache_read, cache_creation_tokens=0, cache_read_tokens=cache_read,
        estimated_cost_usd=Decimal(str(cost)), latency_ms=latency,
        agent=agent, tier=tier, route_reason=reason, fell_back=fell_back,
    )


@pytest.mark.asyncio
async def test_spend_is_broken_down_and_savings_are_estimated(db_session):
    org, admin = await create_org_admin(db_session)
    conversation = AIConversation(organization_id=org.id, user_id=admin.id, title="t")
    db_session.add(conversation)
    await db_session.flush()

    rows = [
        _usage(org.id, admin.id, conversation.id, model="claude-haiku-4-5", tier="fast", agent=None,
               reason="AUTO: a plain question", cost=0.0035),
        _usage(org.id, admin.id, conversation.id, model="claude-sonnet-5", tier="balanced", agent="developer",
               reason="AUTO: the developer agent works through TM1 tools", cost=0.0105, cache_read=20000),
        _usage(org.id, admin.id, conversation.id, model="claude-sonnet-5", tier="balanced", agent="developer",
               reason="BEST chosen; fell back", cost=0.0105, fell_back=True),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.flush()

    report = await ai_cost_report(db_session, org.id, 30)

    assert report["requests"] == 3
    assert report["total_cost_usd"] == pytest.approx(0.0245)
    developer = next(a for a in report["by_agent"] if a["name"] == "developer")
    assert developer["requests"] == 2 and developer["cost_per_request_usd"] == pytest.approx(0.0105)
    assert {t["name"] for t in report["by_tier"]} == {"fast", "balanced"}
    assert report["fallback_rate"] == pytest.approx(1 / 3, abs=1e-4)
    # 20k cached prompt tokens read at a tenth of the input price.
    assert report["cache_savings_usd"] > 0
    # AUTO sent two turns below BEST; priced at Opus they would have cost more.
    assert report["auto_routing"]["requests"] == 2
    assert report["auto_routing"]["estimated_savings_usd"] > 0
    assert "estimate" in report["auto_routing"]["assumption"]


@pytest.mark.asyncio
async def test_another_organizations_spend_is_not_included(db_session):
    org, admin = await create_org_admin(db_session)
    other = await create_organization(db_session)

    report = await ai_cost_report(db_session, other.id, 30)

    assert report["requests"] == 0 and report["total_cost_usd"] == 0


@pytest.mark.asyncio
async def test_the_cost_endpoint_needs_monitoring_access(client, db_session):
    org, admin = await create_org_admin(db_session)

    response = await client.get("/monitoring/ai-costs", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    assert "auto_routing" in response.json()["data"]
