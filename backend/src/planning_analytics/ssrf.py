"""Endpoint validation for customer-supplied MCP URLs.

IBM's Planning Analytics MCP server is a *remote* server, so its URL is
configuration a customer provides. That makes this a server-side request
forgery surface: whatever URL is stored here, PA-Copilot's own backend
will connect to, from inside the deployment's network, with the
deployment's own network position.

The specific prize on a cloud host is the instance metadata service
(169.254.169.254 on AWS/GCP/Azure), which hands out cloud credentials to
anything that can make an HTTP request from the instance. Blocking
loopback alone does not stop that; link-local must be blocked explicitly.

Two rules that matter more than the block-list itself:

* **Resolve before deciding.** A hostname like `metadata.example.com`
  can have an A record pointing at 169.254.169.254. Validating the
  string alone passes it straight through, so every resolved address is
  checked, not just literals.

* **Only an administrator sets this.** The LLM cannot supply an MCP URL
  — there is no tool that accepts one. This module is the second line;
  the first is that the value never comes from model output.

A residual TOCTOU gap remains and is documented rather than papered
over: DNS can change between validation and connection. Closing it
properly needs a pinned-IP connector, which is noted as a limitation.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.core.exceptions import ValidationException

ALLOWED_SCHEMES = frozenset({"https"})

#: http is permitted only when explicitly enabled for local development.
#: Never in production — an MCP exchange carries an OAuth bearer token.
_DEV_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        # Cloud metadata, by the names that resolve to the link-local
        # address on each provider.
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)


@dataclass(frozen=True)
class EndpointValidation:
    url: str
    hostname: str
    port: int
    resolved: tuple[str, ...]


def _is_blocked_address(address: str) -> tuple[bool, str]:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True, "not a valid IP address"

    # Each of these is checked explicitly rather than relying on
    # is_private alone, because the reason matters in the error and
    # because is_private does not cover link-local on every version.
    if ip.is_loopback:
        return True, "loopback address"

    if ip.is_link_local:
        # 169.254.0.0/16 — the cloud metadata range.
        return True, "link-local address (cloud metadata range)"

    if ip.is_private:
        return True, "private network address"

    if ip.is_reserved:
        return True, "reserved address"

    if ip.is_multicast:
        return True, "multicast address"

    if ip.is_unspecified:
        return True, "unspecified address (0.0.0.0)"

    return False, ""


def validate_mcp_endpoint(
    url: str,
    *,
    allow_insecure_http: bool = False,
    allow_private_networks: bool = False,
) -> EndpointValidation:
    """Validate an MCP endpoint URL, or raise.

    `allow_private_networks` exists for genuine enterprise deployments
    where the MCP server really is on an internal network (IBM Planning
    Analytics Local). It is an explicit, administrator-set deployment
    setting — never a per-request argument, and never derived from user
    input. Even then, loopback and link-local stay blocked, because no
    legitimate PA deployment lives there and they are the actual attack
    targets.
    """

    if not url or not isinstance(url, str):
        raise ValidationException("An MCP endpoint URL is required.")

    if len(url) > 2000:
        raise ValidationException("The MCP endpoint URL is too long.")

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise ValidationException("The MCP endpoint URL could not be parsed.")

    permitted = _DEV_SCHEMES if allow_insecure_http else ALLOWED_SCHEMES

    if parts.scheme.lower() not in permitted:
        # Catches file://, gopher://, ftp:// and the rest in one place.
        raise ValidationException(
            f"The MCP endpoint must use {'https' if not allow_insecure_http else 'http or https'}."
        )

    hostname = (parts.hostname or "").lower().strip(".")

    if not hostname:
        raise ValidationException("The MCP endpoint URL has no hostname.")

    if hostname in _BLOCKED_HOSTNAMES:
        raise ValidationException(
            "The MCP endpoint may not point at the local machine."
        )

    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        raise ValidationException("The MCP endpoint port is not valid.")

    if not 1 <= port <= 65535:
        raise ValidationException("The MCP endpoint port is not valid.")

    # Resolve, then judge every address. A hostname that resolves to a
    # blocked address is the whole point of this step — checking the
    # literal string would miss it entirely.
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationException(
            "The MCP endpoint hostname could not be resolved."
        )

    resolved = tuple(sorted({info[4][0] for info in infos}))

    if not resolved:
        raise ValidationException(
            "The MCP endpoint hostname did not resolve to any address."
        )

    for address in resolved:
        blocked, reason = _is_blocked_address(address)

        if not blocked:
            continue

        # Loopback and link-local are never allowed, even for an
        # internal enterprise deployment.
        always_blocked = "loopback" in reason or "link-local" in reason

        if allow_private_networks and not always_blocked:
            continue

        raise ValidationException(
            f"The MCP endpoint resolves to a {reason}, which is not allowed."
        )

    return EndpointValidation(
        url=url.strip(),
        hostname=hostname,
        port=port,
        resolved=resolved,
    )


def assert_redirect_allowed(
    location: str,
    *,
    allow_insecure_http: bool = False,
    allow_private_networks: bool = False,
) -> EndpointValidation:
    """Re-validate a redirect target before following it.

    Redirects are the practical way around endpoint validation: the
    configured URL is a perfectly ordinary public host, and it answers
    `302 Location: http://169.254.169.254/`. Validating only the
    configured URL and then letting the HTTP client follow redirects
    hands the attacker exactly what the check was meant to prevent.

    The client is therefore configured not to follow redirects at all,
    and any redirect is put back through full validation here — same
    rules, including DNS resolution of the new host.
    """

    return validate_mcp_endpoint(
        location,
        allow_insecure_http=allow_insecure_http,
        allow_private_networks=allow_private_networks,
    )


#: Honest statement of what endpoint validation does and does not
#: achieve, so the limitation is not quietly forgotten.
#:
#: Validation resolves DNS and checks every resolved address, then the
#: connection is made by hostname. Between those two steps DNS can
#: change (DNS rebinding), so a determined attacker controlling the
#: authoritative nameserver for a host they also control can still aim
#: the second lookup somewhere else.
#:
#: Closing that fully requires connecting to a *pinned, validated IP*
#: while still presenting the original hostname for TLS SNI and
#: certificate verification. That needs a custom transport/connector,
#: which is not implemented. Mitigations in place: HTTPS is mandatory
#: (so a rebound host fails certificate validation for the original
#: name), redirects are refused rather than followed, and only an
#: administrator can set the endpoint.
SSRF_RESIDUAL_RISK = (
    "DNS rebinding is not fully prevented: validation resolves and checks "
    "every address, but the connection is then made by hostname. Full "
    "prevention requires pinning the connection to a validated IP while "
    "preserving TLS SNI, which is not implemented."
)
