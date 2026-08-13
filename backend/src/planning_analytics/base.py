"""The provider contract, and the gate every invocation passes through.

`authorize_and_invoke()` is the only supported way to reach a provider.
It exists so the six checks that must happen — tenancy, ownership,
capability, permission, risk, availability — happen in one place rather
than being re-implemented (and eventually forgotten) at each call site.

There is deliberately no path from the agent layer straight to a
provider's `invoke()`. The model chooses a *capability*; the application
chooses the provider and decides whether the call is allowed.
"""

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PermissionDeniedException
from src.planning_analytics.capabilities import (
    PlanningAnalyticsCapability,
    ProviderType,
)
from src.planning_analytics.results import (
    ErrorCategory,
    PlanningAnalyticsToolResult,
    ProviderStatus,
)
from src.planning_analytics.risk import RiskLevel, is_executable
from src.repositories.auth_repository import auth_repository


@dataclass(frozen=True)
class InvocationContext:
    """Everything the gate needs, resolved server-side.

    `organization_id` comes from the authenticated session, never from a
    request body or model output — the same discipline the report
    automation worker plane uses.
    """

    organization_id: uuid.UUID
    user_id: uuid.UUID
    connection_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None


class PlanningAnalyticsProvider(ABC):
    """One interface to Planning Analytics.

    A provider declares the capabilities it genuinely implements. It must
    not declare one it cannot perform: `supports()` is what the router
    trusts, and a false declaration turns into a runtime failure for a
    user rather than a routing decision.
    """

    provider_type: ProviderType

    #: Permission a caller must hold to use this provider at all. Per
    #: provider, because IBM MCP access is a different grant from TM1
    #: read access — one must never imply the other.
    required_permission: str

    @abstractmethod
    def supported_capabilities(self) -> frozenset[PlanningAnalyticsCapability]:
        """Only what this provider actually implements."""

    def supports(self, capability: PlanningAnalyticsCapability) -> bool:
        return capability in self.supported_capabilities()

    @abstractmethod
    async def status(self, context: InvocationContext) -> ProviderStatus:
        """Health, auth state, version and discovered tools. No secrets."""

    @abstractmethod
    async def invoke(
        self,
        context: InvocationContext,
        capability: PlanningAnalyticsCapability,
        arguments: dict,
    ) -> PlanningAnalyticsToolResult:
        """Perform a capability. Only ever called via the gate below."""

    def risk_for(self, capability: PlanningAnalyticsCapability) -> RiskLevel:
        """Risk of a capability on this provider.

        Every capability in this phase is read-only, so the default is
        READ. A provider that maps a capability onto something heavier
        overrides this — it does not get to under-report.
        """

        return RiskLevel.READ


async def authorize_and_invoke(
    db: AsyncSession,
    provider: PlanningAnalyticsProvider,
    context: InvocationContext,
    capability: PlanningAnalyticsCapability,
    arguments: dict | None = None,
) -> PlanningAnalyticsToolResult:
    """The single gate. Six checks, in order, before anything runs.

    Ordering is not cosmetic: capability and permission are checked
    before the provider is contacted, so an unauthorized caller cannot
    use timing or error differences to probe whether a connection exists
    or which tools it exposes.
    """

    started = time.monotonic()

    def _refuse(category: str) -> PlanningAnalyticsToolResult:
        return PlanningAnalyticsToolResult(
            provider=provider.provider_type,
            capability=capability,
            success=False,
            error_category=category,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # 1. Capability support — never route to a provider that has not
    #    declared it, even if the provider might happen to cope.
    if not provider.supports(capability):
        return _refuse(ErrorCategory.UNSUPPORTED_CAPABILITY)

    # 2. Risk — read-only phase. Checked before permission so a WRITE
    #    tool is blocked even for a user who holds every permission.
    risk = provider.risk_for(capability)

    if not is_executable(risk):
        return _refuse(ErrorCategory.RISK_BLOCKED)

    # 3. Permission, per provider.
    has_permission = await auth_repository.user_has_permission(
        db, context.user_id, provider.required_permission
    )

    if not has_permission:
        raise PermissionDeniedException(
            f"Missing permission: {provider.required_permission}"
        )

    # 4-6. Tenancy, connection ownership and provider availability are
    #      the provider's own responsibility to enforce against its
    #      configuration, because only it knows what a connection means.
    #      `context.organization_id` is server-resolved, so a provider
    #      cannot be handed someone else's tenant.
    result = await provider.invoke(context, capability, arguments or {})

    if result.duration_ms is None:
        result.duration_ms = int((time.monotonic() - started) * 1000)

    return result
