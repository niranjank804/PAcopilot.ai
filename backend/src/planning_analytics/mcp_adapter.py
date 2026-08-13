"""IBM Planning Analytics MCP adapter — discovery and read-only calls.

What is verified from IBM's own sources, and what is not:

VERIFIED (github.com/IBM/mcp, and IBM's April 2026 announcement):
  * An "IBM Planning Analytics MCP Server" exists and is a **remote**
    server — hence the SSRF surface this module guards.
  * It "Requires PA Agent feature addon entitlement", and the
    announcement ties access to the IBM Planning Analytics Assistant
    licence.
  * OAuth is the authentication mechanism.
  * Four tool categories: Modeling, Analysis, Workflow, Reporting.

NOT VERIFIED:
  * **The individual tool names.** IBM's tool reference
    (ibm.com/docs/en/planning-analytics/3.1.0?topic=assistant-mcp-tools)
    returns HTTP 403 to unauthenticated fetches, and the IBM/mcp
    repository is a listing with no tool manifest.

That gap is why this adapter hard-codes no tool list. The server is the
runtime authority: `discover()` asks it what it has, and `risk.py`
classifies whatever comes back. A tool IBM adds tomorrow is therefore
discovered, displayed, and — if it matches no rule — inert.

The transport here is deliberately minimal and dependency-free: JSON-RPC
2.0 over HTTP, which is what MCP specifies. It is not a full MCP client
and does not pretend to be; it implements `initialize`, `tools/list` and
`tools/call` because those are what discovery and a read-only call need.
"""

import time
from typing import Any

from src.core.config import settings
from src.core.logging import app_logger
from src.planning_analytics.base import (
    InvocationContext,
    PlanningAnalyticsProvider,
)
from src.planning_analytics.capabilities import (
    ConnectionHealth,
    PlanningAnalyticsCapability,
    ProviderType,
)
from src.planning_analytics.results import (
    DiscoveredTool,
    ErrorCategory,
    PlanningAnalyticsToolResult,
    ProviderStatus,
)
from src.planning_analytics.risk import assess
from src.planning_analytics.ssrf import (
    assert_redirect_allowed,
    validate_mcp_endpoint,
)

#: IBM's four announced categories, used only to group tools for display.
#: Never used for risk — risk comes from risk.py.
_CATEGORY_HINTS = {
    "modeling": "Modeling",
    "model": "Modeling",
    "analy": "Analysis",
    "impact": "Analysis",
    "outlier": "Analysis",
    "workflow": "Workflow",
    "approv": "Workflow",
    "review": "Workflow",
    "report": "Reporting",
}

#: Signals that the failure is entitlement, not credentials. IBM gates
#: MCP behind a licence, so an authenticated user can still be refused —
#: reporting that as an auth failure sends admins to reset a password
#: that was never wrong.
_ENTITLEMENT_SIGNALS = (
    "entitlement",
    "licen",  # licence / license
    "not subscribed",
    "feature addon",
    "pa agent",
    "assistant license",
)


class MCPTransportError(Exception):
    """Transport-level failure. Never carries a token or header."""

    def __init__(self, message: str, *, category: str):
        self.category = category

        super().__init__(message)


class MCPClient:
    """Minimal JSON-RPC 2.0 MCP client over HTTP.

    Injectable `transport` so the protocol can be unit-tested against a
    mock server without a network — and so a mocked success can never be
    mistaken for real IBM compatibility, because the live tests are
    marked separately.
    """

    PROTOCOL_VERSION = "2025-06-18"

    def __init__(
        self,
        endpoint: str,
        *,
        access_token: str | None = None,
        transport: Any = None,
        timeout_seconds: float = 30.0,
        allow_insecure_http: bool = False,
        allow_private_networks: bool = False,
    ):
        # Validated at construction: there is no code path that reaches
        # the network with an unvalidated URL.
        self.validated = validate_mcp_endpoint(
            endpoint,
            allow_insecure_http=allow_insecure_http,
            allow_private_networks=allow_private_networks,
        )
        self.endpoint = self.validated.url
        self._access_token = access_token
        self._transport = transport
        self.timeout_seconds = timeout_seconds
        self._request_id = 0
        self._initialized = False
        self.server_info: dict = {}

    def _next_id(self) -> int:
        self._request_id += 1

        return self._request_id

    async def _send(self, method: str, params: dict | None = None) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": self.PROTOCOL_VERSION,
        }

        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        if self._transport is None:
            raise MCPTransportError(
                "No MCP transport is configured.",
                category=ErrorCategory.SYSTEM_ERROR,
            )

        # The transport never sees the logger. Nothing in this method
        # logs `headers` — that is the only place the bearer token
        # exists, and it must not reach a log sink.
        response = await self._transport(
            self.endpoint, payload, headers, self.timeout_seconds
        )

        if not isinstance(response, dict):
            raise MCPTransportError(
                "The MCP server returned a malformed response.",
                category=ErrorCategory.SYSTEM_ERROR,
            )

        if "error" in response:
            error = response["error"] or {}
            message = str(error.get("message", ""))[:300]

            raise MCPTransportError(
                message or "The MCP server returned an error.",
                category=_categorize(message, error.get("code")),
            )

        return response.get("result") or {}

    async def initialize(self) -> dict:
        result = await self._send(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pa-copilot", "version": "0.1.0"},
            },
        )

        self._initialized = True
        self.server_info = result.get("serverInfo") or {}

        return result

    async def list_tools(self) -> list[dict]:
        if not self._initialized:
            await self.initialize()

        result = await self._send("tools/list")
        tools = result.get("tools")

        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if not self._initialized:
            await self.initialize()

        return await self._send(
            "tools/call", {"name": name, "arguments": arguments}
        )


def _categorize(message: str, code: Any = None) -> str:
    lowered = (message or "").lower()

    if any(signal in lowered for signal in _ENTITLEMENT_SIGNALS):
        return ErrorCategory.ENTITLEMENT

    if "unauthor" in lowered or "forbidden" in lowered or code in (401, 403):
        return ErrorCategory.AUTHENTICATION

    if "not found" in lowered or code == 404:
        return ErrorCategory.EXPECTED_NOT_FOUND

    if "timeout" in lowered or "timed out" in lowered:
        return ErrorCategory.TIMEOUT

    return ErrorCategory.SYSTEM_ERROR


def _category_for(tool_name: str) -> str | None:
    lowered = (tool_name or "").lower()

    for needle, label in _CATEGORY_HINTS.items():
        if needle in lowered:
            return label

    return None


def normalize_tools(raw_tools: list[dict]) -> list[DiscoveredTool]:
    """Turn a server's tool list into PA-Copilot's representation.

    Every field that reaches the UI is length-capped, and the
    description is carried for display only — `assess()` is called with
    the *name alone*, so a description claiming "safe, read-only" cannot
    influence the risk verdict.
    """

    discovered: list[DiscoveredTool] = []

    for raw in raw_tools:
        if not isinstance(raw, dict):
            continue

        name = str(raw.get("name") or "").strip()

        if not name:
            continue

        assessment = assess(name)

        discovered.append(
            DiscoveredTool(
                # Preserved verbatim for audit, even though it is
                # untrusted — truncated only to bound storage.
                original_name=name[:200],
                description=str(raw.get("description") or "")[:1000],
                risk=assessment.risk,
                executable=assessment.executable,
                reason=assessment.reason,
                category=_category_for(name),
                input_schema=(
                    raw.get("inputSchema")
                    if isinstance(raw.get("inputSchema"), dict)
                    else None
                ),
            )
        )

    return discovered


class IBMPlanningAnalyticsMCPProvider(PlanningAnalyticsProvider):
    """Read-only IBM MCP provider.

    Declares no capabilities up front. IBM does not publish a tool
    manifest that can be fetched without authentication, so what this
    provider can do is only knowable after `discover()` has run against
    a real, entitled connection. Declaring capabilities before that
    would be exactly the fiction this phase exists to avoid.
    """

    provider_type = ProviderType.IBM_MCP
    required_permission = "pa.mcp.read"

    def __init__(self, client: MCPClient | None = None):
        self._client = client
        self._tools: list[DiscoveredTool] = []
        self._discovered = False

    def supported_capabilities(self) -> frozenset[PlanningAnalyticsCapability]:
        # Empty until a live discovery proves otherwise. The router
        # therefore never sends work here on the strength of the code
        # merely existing.
        return frozenset()

    async def discover(self, context: InvocationContext) -> ProviderStatus:
        """Ask the server what it exposes, and classify the answer."""

        status = ProviderStatus(
            provider=self.provider_type,
            health=ConnectionHealth.UNKNOWN,
        )

        if self._client is None:
            status.health = ConnectionHealth.UNSUPPORTED
            status.notes.append(
                "No IBM MCP connection is configured for this organization."
            )

            return status

        started = time.monotonic()

        try:
            init = await self._client.initialize()

            info = init.get("serverInfo") or {}
            status.provider_version = str(info.get("version") or "")[:50] or None
            status.tenant = str(info.get("name") or "")[:100] or None
            status.authenticated = True

            raw_tools = await self._client.list_tools()

            self._tools = normalize_tools(raw_tools)
            self._discovered = True
            status.tools = self._tools
            status.health = ConnectionHealth.CONNECTED

            blocked = sum(1 for tool in self._tools if not tool.executable)

            if blocked:
                status.notes.append(
                    f"{blocked} tool(s) discovered but blocked in this phase "
                    "(write, destructive or unclassified)."
                )

            app_logger.info(
                "pa_mcp discovery ok "
                f"organization_id={context.organization_id} "
                f"tools={len(self._tools)} blocked={blocked}"
            )
        except MCPTransportError as exc:
            status.last_error = str(exc)[:300]

            if exc.category == ErrorCategory.ENTITLEMENT:
                status.health = ConnectionHealth.LICENSE_OR_ENTITLEMENT_REQUIRED
                status.notes.append(
                    "IBM ties Planning Analytics MCP access to the Planning "
                    "Analytics Assistant licence / PA Agent feature addon."
                )
            elif exc.category == ErrorCategory.AUTHENTICATION:
                status.health = ConnectionHealth.AUTHENTICATION_FAILED
            elif exc.category == ErrorCategory.UNREACHABLE:
                status.health = ConnectionHealth.UNREACHABLE
            else:
                status.health = ConnectionHealth.TOOL_DISCOVERY_FAILED
        except Exception as exc:  # noqa: BLE001
            # Type only — an exception message from an HTTP client can
            # embed the URL, and the URL can embed a token.
            status.health = ConnectionHealth.UNKNOWN
            status.last_error = type(exc).__name__

        status.notes.append(
            f"discovery took {int((time.monotonic() - started) * 1000)}ms"
        )

        return status

    async def status(self, context: InvocationContext) -> ProviderStatus:
        return await self.discover(context)

    async def invoke(
        self,
        context: InvocationContext,
        capability: PlanningAnalyticsCapability,
        arguments: dict,
    ) -> PlanningAnalyticsToolResult:
        """Refuses everything in this phase.

        Capability-to-tool mapping needs IBM's real tool names, which
        are not published for unauthenticated retrieval. Guessing them
        would produce an adapter that appears to work and silently calls
        the wrong thing, so it declines instead.
        """

        return PlanningAnalyticsToolResult(
            provider=self.provider_type,
            capability=capability,
            success=False,
            error_category=ErrorCategory.UNSUPPORTED_CAPABILITY,
            warnings=[
                "IBM MCP capability execution is not enabled. Tool discovery "
                "is implemented; capability mapping requires a live, entitled "
                "IBM MCP connection to establish the real tool names."
            ],
        )


def build_http_transport():
    """A real HTTP transport, created only when actually needed.

    Kept out of module import so the adapter and its tests have no
    network dependency, and so no transport exists unless a configured
    connection asks for one.
    """

    import httpx2

    async def transport(
        endpoint: str, payload: dict, headers: dict, timeout: float
    ) -> dict:
        # follow_redirects=False is load-bearing, not a default. A
        # redirect is the practical way around endpoint validation: the
        # configured host is ordinary and public, and answers
        # "302 Location: http://169.254.169.254/". Any redirect is
        # re-validated below instead of being followed.
        async with httpx2.AsyncClient(
            timeout=timeout, follow_redirects=False
        ) as client:
            try:
                response = await client.post(
                    endpoint, json=payload, headers=headers
                )
            except Exception as exc:  # noqa: BLE001
                raise MCPTransportError(
                    f"Could not reach the MCP server ({type(exc).__name__}).",
                    category=ErrorCategory.UNREACHABLE,
                )

            if 300 <= response.status_code < 400:
                location = response.headers.get("location", "")

                try:
                    assert_redirect_allowed(location)
                except Exception:
                    raise MCPTransportError(
                        "The MCP server redirected to a destination that is "
                        "not allowed.",
                        category=ErrorCategory.SYSTEM_ERROR,
                    )

                raise MCPTransportError(
                    "The MCP server redirected; redirects are not followed.",
                    category=ErrorCategory.SYSTEM_ERROR,
                )

            if response.status_code in (401, 403):
                raise MCPTransportError(
                    f"The MCP server refused the request (HTTP "
                    f"{response.status_code}).",
                    category=_categorize(response.text[:300], response.status_code),
                )

            try:
                return response.json()
            except ValueError:
                raise MCPTransportError(
                    "The MCP server returned a non-JSON response.",
                    category=ErrorCategory.SYSTEM_ERROR,
                )

    return transport


#: Present so the setting is discoverable, but deliberately not read at
#: import: an unconfigured deployment must have no MCP client at all.
MCP_ENABLED_SETTING = "PA_MCP_ENABLED"


def is_mcp_configured() -> bool:
    return bool(getattr(settings, MCP_ENABLED_SETTING, False))
