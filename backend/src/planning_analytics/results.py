"""Provider-neutral result and descriptor types.

`PlanningAnalyticsToolResult` carries provenance as a first-class field
rather than as a formatted string, so an answer can say *"Source: TM1
REST / cube metadata"* truthfully. The rule the tests enforce is that
`provider` is stamped by the adapter that actually ran the call — it is
never passed in by a caller and never inferred, so an answer cannot
claim IBM MCP produced something TM1 REST did.
"""

from dataclasses import dataclass, field
from typing import Any

from src.planning_analytics.capabilities import (
    ConnectionHealth,
    PlanningAnalyticsCapability,
    ProviderType,
)
from src.planning_analytics.risk import RiskLevel


class ErrorCategory:
    """Separates "the answer is legitimately nothing" from "we broke".

    Folding EXPECTED_NOT_FOUND into system errors is how a monitoring
    dashboard grows a permanent false error rate that everyone learns to
    ignore.
    """

    NONE = "NONE"
    EXPECTED_NOT_FOUND = "EXPECTED_NOT_FOUND"
    AUTHENTICATION = "AUTHENTICATION"
    ENTITLEMENT = "ENTITLEMENT"
    UNREACHABLE = "UNREACHABLE"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RISK_BLOCKED = "RISK_BLOCKED"
    TIMEOUT = "TIMEOUT"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass
class PlanningAnalyticsToolResult:
    provider: ProviderType
    capability: PlanningAnalyticsCapability
    success: bool
    tool_name: str | None = None
    data: Any = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error_category: str = ErrorCategory.NONE
    #: Human-readable provenance, e.g. "IBM MCP / list_cubes".
    source_reference: str = ""
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.source_reference:
            label = {
                ProviderType.TM1_REST: "TM1 REST",
                ProviderType.IBM_MCP: "IBM MCP",
                ProviderType.PAX: "PAx",
                ProviderType.PAFE_WORKER: "PAfE worker",
            }.get(self.provider, self.provider.value)

            self.source_reference = (
                f"{label} / {self.tool_name}" if self.tool_name else label
            )


@dataclass(frozen=True)
class DiscoveredTool:
    """One tool as the server actually advertised it.

    `original_name` is preserved verbatim for audit: when IBM renames a
    tool, the audit trail must still say what was really invoked.
    `description` is stored for display only and is never an input to
    classification — see risk.py.
    """

    original_name: str
    description: str
    risk: RiskLevel
    executable: bool
    reason: str
    category: str | None = None
    input_schema: dict | None = None


@dataclass
class ProviderStatus:
    """What a provider reports about itself. No secrets, ever."""

    provider: ProviderType
    health: ConnectionHealth
    supported_capabilities: list[PlanningAnalyticsCapability] = field(
        default_factory=list
    )
    unsupported_capabilities: list[PlanningAnalyticsCapability] = field(
        default_factory=list
    )
    authenticated: bool = False
    provider_version: str | None = None
    environment: str | None = None
    tenant: str | None = None
    tools: list[DiscoveredTool] = field(default_factory=list)
    last_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_safe_dict(self) -> dict:
        """Serialization for API/UI. Deliberately allow-list shaped.

        Built by naming each field rather than dumping the object, so a
        field added later (a token, a header, a raw response) cannot
        become part of the API response by accident.
        """

        return {
            "provider": self.provider.value,
            "health": self.health.value,
            "authenticated": self.authenticated,
            "provider_version": self.provider_version,
            "environment": self.environment,
            "tenant": self.tenant,
            "supported_capabilities": [
                c.value for c in self.supported_capabilities
            ],
            "unsupported_capabilities": [
                c.value for c in self.unsupported_capabilities
            ],
            "tools": [
                {
                    "name": tool.original_name,
                    "description": tool.description[:500],
                    "risk": tool.risk.value,
                    "executable": tool.executable,
                    "reason": tool.reason,
                    "category": tool.category,
                }
                for tool in self.tools
            ],
            "tool_count": len(self.tools),
            "executable_tool_count": sum(1 for t in self.tools if t.executable),
            "blocked_tool_count": sum(1 for t in self.tools if not t.executable),
            "last_error": self.last_error,
            "notes": self.notes,
        }
