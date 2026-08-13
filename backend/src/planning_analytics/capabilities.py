"""What a Planning Analytics provider can be asked to do.

Capabilities are named by *intent*, not by transport, so the agent layer
never has to know whether an answer came from TM1 REST, IBM MCP or PAx.
A provider declares only what it actually supports; the registry refuses
to route a capability to a provider that has not declared it, which is
what stops a "supported" list from drifting into fiction.
"""

from enum import Enum


class ProviderType(str, Enum):
    """The distinct interfaces to Planning Analytics.

    These are separate products with separate licensing and separate
    failure modes. Collapsing any two of them would make provenance
    meaningless — see `results.py`.
    """

    #: The existing, validated TM1 REST integration (src/tm1/).
    TM1_REST = "tm1_rest"

    #: IBM's remote Planning Analytics MCP server. Optional, OAuth, and
    #: gated behind the IBM Planning Analytics Assistant licence.
    IBM_MCP = "ibm_mcp"

    #: IBM's PAx COM automation API. Windows-and-Excel-only by nature, so
    #: it can never run in the cloud control plane — see docs.
    PAX = "pax"

    #: PA-Copilot's own Windows worker driving Excel + PAfE.
    PAFE_WORKER = "pafe_worker"


class PlanningAnalyticsCapability(str, Enum):
    """Read-only capabilities. This phase adds no write capability.

    There is deliberately no `execute_process`, `create_view`,
    `write_cells` or `publish_report` member. A capability that does not
    exist cannot be routed, requested, or accidentally enabled by
    configuration — the absence is the control.
    """

    GET_CONNECTION_METADATA = "get_connection_metadata"
    LIST_CUBES = "list_cubes"
    GET_CUBE_METADATA = "get_cube_metadata"
    LIST_DIMENSIONS = "list_dimensions"
    GET_DIMENSION_METADATA = "get_dimension_metadata"
    LIST_VIEWS = "list_views"
    GET_VIEW_METADATA = "get_view_metadata"
    EXECUTE_MDX_READONLY = "execute_mdx_readonly"
    GET_PROCESS_METADATA = "get_process_metadata"
    GET_PROCESS_STATUS = "get_process_status"


#: Every capability in this phase is read-only by construction.
READ_ONLY_CAPABILITIES = frozenset(PlanningAnalyticsCapability)


class ConnectionHealth(str, Enum):
    """Distinguishes the failures an operator must act on differently.

    `LICENSE_OR_ENTITLEMENT_REQUIRED` is separate from
    `AUTHENTICATION_FAILED` because IBM gates MCP behind the Planning
    Analytics Assistant licence: credentials can be perfectly valid and
    the server still refuse. Reporting that as an auth failure would send
    an administrator to reset a password that was never wrong.
    """

    CONNECTED = "CONNECTED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    UNREACHABLE = "UNREACHABLE"
    TOOL_DISCOVERY_FAILED = "TOOL_DISCOVERY_FAILED"
    LICENSE_OR_ENTITLEMENT_REQUIRED = "LICENSE_OR_ENTITLEMENT_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
