"""Turn whatever a user pasted into the Address field into a hostname.

People copy the address out of the browser bar, so the field receives
``https://us-east-1.planninganalytics.saas.ibm.com/`` or a full REST URL
far more often than a bare hostname. TM1py then builds
``https://<address>:<port>`` from it and the connection fails with nothing
to say why. Normalising here, once, keeps every caller honest.
"""

import ipaddress
from dataclasses import dataclass

# Every IBM Planning Analytics as a Service region lives under this domain
# (us-east-1., eu-central-1., ap-southeast-2. ...).
SAAS_HOST_SUFFIX = ".planninganalytics.saas.ibm.com"


@dataclass(frozen=True)
class ParsedAddress:
    host: str
    # Present only when a full PA SaaS REST URL was pasted:
    # https://<host>/api/<tenant>/v0/tm1/<database>/...
    tenant: str | None = None
    database: str | None = None


def parse_address(raw: str) -> ParsedAddress:
    value = raw.strip()

    if "://" in value:
        value = value.split("://", 1)[1]

    host, _, path = value.partition("/")
    segments = [segment for segment in path.split("/") if segment]

    if (
        len(segments) >= 5
        and segments[0] == "api"
        and segments[2] == "v0"
        and segments[3] == "tm1"
    ):
        return ParsedAddress(host=host, tenant=segments[1], database=segments[4])

    # Planning Analytics on Cloud REST URL:
    # https://<host>/tm1/api/<database>/api/v1/...
    if len(segments) >= 3 and segments[0] == "tm1" and segments[1] == "api":
        return ParsedAddress(host=host, database=segments[2])

    return ParsedAddress(host=host)


def is_saas_host(address: str) -> bool:
    # Parsed first: rows saved before normalisation existed still carry the
    # scheme or trailing slash they were pasted with.
    return parse_address(address).host.lower().endswith(SAAS_HOST_SUFFIX)


def is_private_address(host: str) -> bool:
    """True when `host` is an IP literal that is not a public address:
    loopback, link-local (cloud metadata), private ranges, reserved,
    multicast, unspecified — or the name `localhost`.

    Hostnames are not resolved here: the check runs on save, where a DNS
    lookup would make every form submit wait on the network. What a
    hostname resolves to is the deployment's network policy to enforce.
    """

    value = host.strip().strip("[]").lower()

    if value == "localhost":
        return True

    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False

    # is_global already excludes private, loopback, link-local, reserved
    # and unspecified ranges; multicast is not "global" in any sense a
    # TM1 server could be reached at, but the stdlib counts it as such.
    return not ip.is_global or ip.is_multicast


PRIVATE_ADDRESS_REFUSED = (
    "This address points at a local or private network, which this "
    "deployment does not reach. Enter the public hostname of your TM1 "
    "server. For a self-hosted deployment whose TM1 is on the same "
    "network, the administrator can set TM1_ALLOW_PRIVATE_ADDRESSES."
)


SAAS_NEEDS_SAAS_TYPE = (
    "This is an IBM Planning Analytics as a Service address. Choose the "
    "'Planning Analytics as a Service' connection type and enter your "
    "tenant ID and database name with your API key — SaaS does not accept "
    "a port or a native TM1 login."
)
