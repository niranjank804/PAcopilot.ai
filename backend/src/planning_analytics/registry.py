"""Provider registry and deterministic capability routing.

Two properties this module is built around:

* **Nothing is instantiated automatically.** The registry holds provider
  *classes*, not live objects. A provider only exists once an
  organization has explicitly enabled and configured it, so an
  unconfigured deployment has no MCP client, no credentials in memory,
  and no way to reach a customer endpoint.

* **Routing is deterministic.** `select_provider()` is ordinary code
  applying a fixed priority. The model is never asked "should I use
  MCP?" — it asks for a capability, and the application decides. An LLM
  router would make provider choice attacker-influencable through the
  conversation, which is precisely the control this phase must keep.

Priority puts native TM1 REST first because it is the only validated
integration. IBM MCP is a fallback, never a silent substitute: if the
two would answer a capability with different semantics, the router does
not swap between them — the caller sees which provider ran, on every
result.
"""

from src.planning_analytics.base import PlanningAnalyticsProvider
from src.planning_analytics.capabilities import (
    PlanningAnalyticsCapability,
    ProviderType,
)
from src.planning_analytics.mcp_adapter import IBMPlanningAnalyticsMCPProvider

#: Classes, not instances. See the module docstring.
PLANNING_ANALYTICS_PROVIDERS: dict[ProviderType, type] = {
    ProviderType.IBM_MCP: IBMPlanningAnalyticsMCPProvider,
}

#: Native TM1 REST is deliberately absent: it already has a complete,
#: validated implementation in src/tm1/ that this phase must not
#: disturb. Wrapping it in an adapter is a later, separate change —
#: registering a half-adapter here would put an untested path in front
#: of the one integration that actually works.
#:
#: PAx is absent for a structural reason, not an ordering one: it is a
#: COM API that only exists inside a Windows Excel process. It cannot be
#: a cloud-side provider at all, and belongs to the worker. See
#: docs/planning-analytics/pax.md.

#: Lower number wins. Validated integrations outrank optional ones.
PROVIDER_PRIORITY: dict[ProviderType, int] = {
    ProviderType.TM1_REST: 10,
    ProviderType.IBM_MCP: 50,
    ProviderType.PAX: 90,
    ProviderType.PAFE_WORKER: 90,
}


def select_provider(
    capability: PlanningAnalyticsCapability,
    available: list[PlanningAnalyticsProvider],
) -> PlanningAnalyticsProvider | None:
    """Pick the highest-priority provider that declares `capability`.

    Returns None rather than falling back to something that has not
    declared support. A caller that receives None reports "no configured
    provider can answer this" — which is a true statement, and better
    than an answer produced by a provider guessing.
    """

    candidates = [
        provider for provider in available if provider.supports(capability)
    ]

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda provider: PROVIDER_PRIORITY.get(provider.provider_type, 1000),
    )


def get_provider_class(provider_type: ProviderType) -> type | None:
    return PLANNING_ANALYTICS_PROVIDERS.get(provider_type)
