"""MCP protocol and discovery, against a mock server.

The mock implements the JSON-RPC shape MCP specifies. It proves *our
adapter* handles the protocol and classifies failures correctly.

It proves nothing whatsoever about IBM compatibility. No test in this
file may be cited as evidence that PA-Copilot works with IBM's Planning
Analytics MCP server — that requires a live entitled connection and is
marked `live_mcp` elsewhere.
"""

import uuid

import pytest

from src.planning_analytics.base import InvocationContext
from src.planning_analytics.capabilities import (
    ConnectionHealth,
    PlanningAnalyticsCapability,
)
from src.planning_analytics.mcp_adapter import (
    IBMPlanningAnalyticsMCPProvider,
    MCPClient,
    MCPTransportError,
)
from src.planning_analytics.results import ErrorCategory
from src.planning_analytics.risk import RiskLevel

ENDPOINT = "https://mcp.example.com/planning-analytics"


@pytest.fixture(autouse=True)
def _resolvable_endpoint(monkeypatch):
    """Make the test endpoint resolve to a public address.

    The SSRF guard resolves DNS before allowing a URL — that is the
    control, not an inconvenience, so it is not weakened with a
    test-only bypass parameter. Production code would then ship a switch
    that disables the check, which is exactly the kind of thing that
    eventually gets set in the wrong place.

    Patching the resolver here keeps these tests hermetic while leaving
    `validate_mcp_endpoint` with no way to skip resolution.
    """

    import socket

    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host == "mcp.example.com":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ]

        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(
        "src.planning_analytics.ssrf.socket.getaddrinfo", fake
    )


@pytest.fixture
def context():
    return InvocationContext(
        organization_id=uuid.uuid4(), user_id=uuid.uuid4()
    )


def make_transport(*, tools=None, error=None, capture=None):
    """A mock MCP server over the injected transport seam."""

    async def transport(endpoint, payload, headers, timeout):
        if capture is not None:
            capture.append({"payload": payload, "headers": headers})

        if error is not None:
            return {"jsonrpc": "2.0", "id": payload["id"], "error": error}

        method = payload["method"]

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {
                        "name": "IBM Planning Analytics MCP",
                        "version": "1.2.3",
                    },
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": tools or []},
            }

        return {"jsonrpc": "2.0", "id": payload["id"], "result": {}}

    return transport


class TestProtocol:

    @pytest.mark.asyncio
    async def test_initialize_reports_server_info(self):
        client = MCPClient(ENDPOINT, transport=make_transport())

        result = await client.initialize()

        assert result["serverInfo"]["version"] == "1.2.3"

    @pytest.mark.asyncio
    async def test_tools_list_auto_initializes(self):
        capture = []
        client = MCPClient(ENDPOINT, transport=make_transport(capture=capture))

        await client.list_tools()

        methods = [entry["payload"]["method"] for entry in capture]

        assert methods == ["initialize", "tools/list"]

    @pytest.mark.asyncio
    async def test_the_bearer_token_is_sent_but_never_returned(self):
        capture = []
        client = MCPClient(
            ENDPOINT, access_token="super-secret-token", transport=make_transport(capture=capture)
        )

        await client.initialize()

        # It must reach the server...
        assert capture[0]["headers"]["Authorization"] == "Bearer super-secret-token"

        # ...and must not be reachable from the client's public surface,
        # which is what the status/API layer serializes.
        assert "super-secret-token" not in repr(client.server_info)

    @pytest.mark.asyncio
    async def test_the_endpoint_is_validated_at_construction(self):
        from src.core.exceptions import ValidationException

        # There is no code path to the network with an unvalidated URL.
        with pytest.raises(ValidationException):
            MCPClient("http://169.254.169.254/", transport=make_transport())


class TestDiscovery:

    @pytest.mark.asyncio
    async def test_discovery_classifies_every_tool(self, context):
        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                transport=make_transport(
                    tools=[
                        {"name": "list_cubes", "description": "List cubes"},
                        {"name": "analyze_cube", "description": "Impact analysis"},
                        {"name": "create_view", "description": "Create a view"},
                        {"name": "delete_sandbox", "description": "Delete"},
                        {"name": "frobnicate", "description": "???"},
                    ]
                ),
            )
        )

        status = await provider.discover(context)

        assert status.health is ConnectionHealth.CONNECTED
        assert status.authenticated is True
        assert status.provider_version == "1.2.3"

        by_name = {tool.original_name: tool for tool in status.tools}

        assert by_name["list_cubes"].risk is RiskLevel.READ
        assert by_name["list_cubes"].executable

        assert by_name["analyze_cube"].risk is RiskLevel.ANALYSIS
        assert by_name["analyze_cube"].executable

        # Write and destructive are discovered and displayed, blocked.
        assert by_name["create_view"].executable is False
        assert by_name["delete_sandbox"].executable is False

        # Unknown fails closed.
        assert by_name["frobnicate"].risk is RiskLevel.UNCLASSIFIED
        assert by_name["frobnicate"].executable is False

    @pytest.mark.asyncio
    async def test_the_safe_dict_never_leaks_a_token(self, context):
        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                access_token="tok-do-not-leak",
                transport=make_transport(
                    tools=[{"name": "list_cubes", "description": "x"}]
                ),
            )
        )

        payload = (await provider.discover(context)).to_safe_dict()

        serialized = str(payload)

        assert "tok-do-not-leak" not in serialized
        assert "Authorization" not in serialized
        assert "Bearer" not in serialized

    @pytest.mark.asyncio
    async def test_blocked_tools_are_counted_for_the_inspector(self, context):
        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                transport=make_transport(
                    tools=[
                        {"name": "list_cubes", "description": ""},
                        {"name": "delete_cube", "description": ""},
                        {"name": "create_view", "description": ""},
                    ]
                ),
            )
        )

        payload = (await provider.discover(context)).to_safe_dict()

        assert payload["tool_count"] == 3
        assert payload["executable_tool_count"] == 1
        assert payload["blocked_tool_count"] == 2

    @pytest.mark.asyncio
    async def test_no_configured_client_reports_unsupported(self, context):
        status = await IBMPlanningAnalyticsMCPProvider().discover(context)

        assert status.health is ConnectionHealth.UNSUPPORTED


class TestFailureClassification:

    @pytest.mark.asyncio
    async def test_entitlement_failure_is_not_reported_as_auth(self, context):
        """IBM gates MCP behind a licence.

        Credentials can be perfectly valid and the server still refuse.
        Reporting that as an auth failure sends an administrator to reset
        a password that was never wrong.
        """

        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                transport=make_transport(
                    error={
                        "code": 403,
                        "message": "PA Agent feature addon entitlement required",
                    }
                ),
            )
        )

        status = await provider.discover(context)

        assert status.health is ConnectionHealth.LICENSE_OR_ENTITLEMENT_REQUIRED
        assert any("licence" in note.lower() for note in status.notes)

    @pytest.mark.asyncio
    async def test_genuine_auth_failure_is_reported_as_auth(self, context):
        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                transport=make_transport(
                    error={"code": 401, "message": "Unauthorized"}
                ),
            )
        )

        status = await provider.discover(context)

        assert status.health is ConnectionHealth.AUTHENTICATION_FAILED

    @pytest.mark.asyncio
    async def test_transport_errors_do_not_leak_the_url(self, context):
        async def exploding(endpoint, payload, headers, timeout):
            raise RuntimeError(
                f"connection failed to {endpoint}?access_token=leaky"
            )

        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(ENDPOINT, transport=exploding)
        )

        status = await provider.discover(context)

        # Type name only — an HTTP client's message can embed the URL,
        # and a URL can embed a token.
        assert status.last_error == "RuntimeError"
        assert "leaky" not in str(status.to_safe_dict())

    @pytest.mark.asyncio
    async def test_a_malformed_response_is_a_system_error(self):
        async def malformed(endpoint, payload, headers, timeout):
            return "not a dict"

        client = MCPClient(ENDPOINT, transport=malformed)

        with pytest.raises(MCPTransportError) as exc_info:
            await client.initialize()

        assert exc_info.value.category == ErrorCategory.SYSTEM_ERROR


class TestExecutionIsRefused:

    @pytest.mark.asyncio
    async def test_invoke_refuses_in_this_phase(self, context):
        provider = IBMPlanningAnalyticsMCPProvider(
            MCPClient(
                ENDPOINT,
                transport=make_transport(
                    tools=[{"name": "list_cubes", "description": ""}]
                ),
            )
        )

        result = await provider.invoke(
            context, PlanningAnalyticsCapability.LIST_CUBES, {}
        )

        assert result.success is False
        assert result.error_category == ErrorCategory.UNSUPPORTED_CAPABILITY
        assert result.warnings
