import asyncio
import uuid

from TM1py import TM1Service

from src.core.config import settings
from src.database.models.tm1_connection import TM1Connection
from src.tm1.addressing import PRIVATE_ADDRESS_REFUSED, is_private_address, parse_address
from src.tm1.crypto import decrypt_password
from src.tm1.exceptions import TM1ConnectionError, TM1ConnectionSuspendedError
from src.tm1.gateway.relay import install as install_gateway_transport
from src.tm1.resilience import call_with_resilience, remove_circuit_breaker

# Gateway connections route TM1py through the gateway; others are untouched.
install_gateway_transport()


def build_tm1_kwargs(connection: TM1Connection, password: str) -> dict:
    """Map a TM1Connection row to TM1py TM1Service kwargs per auth mode.

    Keeping the mapping in one factory keeps every caller (and future auth
    modes: CAM namespace, IBM Cloud v12 API keys) out of TM1py specifics.
    """

    if connection.authentication_type == "v12_saas":
        # PA as a Service (v12): pass ONLY base_url + user "apikey" + the API
        # key as password. Passing tenant/database as their own kwargs routes
        # TM1py's _determine_auth_mode() into the v12/CPD branch, which then
        # demands cpd_url — the BASIC_API_KEY branch requires none of
        # (auth_url, instance, database, api_key, iam_url, pa_url, tenant)
        # to be set. Found live against a real PA SaaS trial (defect #002).
        # Parsed rather than used raw: rows saved before normalisation still
        # carry a pasted "https://" or trailing slash, which would put "//"
        # into the URL and fail every call.
        host = parse_address(connection.address).host

        return {
            "base_url": (
                f"https://{host}/api/{connection.tenant}"
                f"/v0/tm1/{connection.database}/"
            ),
            "user": "apikey",
            "password": password,
            "ssl": True,
            "verify": True,
            **_timeout_kwargs(),
        }

    if connection.authentication_type == PA_CLOUD:
        # Planning Analytics on Cloud with an IBM non-interactive account.
        # IBM's gateway serves each database under /tm1/api/<database>/ and
        # authenticates non-interactive accounts through CAM with the LDAP
        # namespace — a plain basic login is rejected. TM1py treats a
        # base_url plus a namespace as CAM and appends /api/v1 itself.
        # async_requests_mode keeps long calls under the gateway's 60-second
        # limit (TM1py's documented setting for IBM Cloud).
        host = parse_address(connection.address).host

        return {
            "base_url": f"https://{host}/tm1/api/{connection.database}/",
            "user": connection.username,
            "password": password,
            "namespace": PA_CLOUD_NAMESPACE,
            "ssl": True,
            "verify": True,
            "async_requests_mode": True,
            **_timeout_kwargs(),
        }

    kwargs = {
        "address": connection.address,
        "port": connection.port,
        "ssl": connection.ssl,
        "user": connection.username,
        "password": password,
        **_timeout_kwargs(),
    }
    if getattr(connection, "gateway_id", None):
        # Inside a company network: TM1py's requests travel through the
        # PA-Copilot gateway there (src/tm1/gateway/relay.py).
        kwargs["pa_gateway"] = str(connection.gateway_id)
    return kwargs


PA_CLOUD = "pa_cloud"
# The namespace IBM assigns non-interactive accounts on PA on Cloud.
PA_CLOUD_NAMESPACE = "LDAP"


def _timeout_kwargs() -> dict:
    """TM1py's own request timeout.

    Without it TM1py waits forever on a socket, and the asyncio timeout
    around the call (src/tm1/resilience.py) only stops *waiting* — the
    thread stays blocked, and each retry starts another, until the pool
    is gone. With it the request itself ends, the thread comes back, and
    TM1 is asked to cancel the operation it was running for us.
    """

    return {
        "timeout": settings.TM1_REQUEST_TIMEOUT_SECONDS,
        "cancel_at_timeout": True,
    }


def _logout_quietly(client: TM1Service) -> None:
    try:
        client.logout()
    except Exception:
        # The session expires on its own; nothing to do about a server
        # that would not end it now.
        pass


async def _refuse_private_destination(connection: TM1Connection) -> None:
    """Refuse to send credentials to a host that resolves to a private,
    loopback or link-local address when this deployment does not allow it.

    Saving a connection only checks IP literals; a hostname such as
    127.0.0.1.nip.io, or the decimal form of an address, passes that check.
    So the name is resolved here, at the moment credentials would be sent.
    A connection through a gateway is reached inside the customer's own
    network and is not subject to this.
    """

    if settings.TM1_ALLOW_PRIVATE_ADDRESSES:
        return
    if getattr(connection, "gateway_id", None) and connection.authentication_type == "native":
        return

    host = parse_address(connection.address).host
    if is_private_address(host):
        raise TM1ConnectionError(PRIVATE_ADDRESS_REFUSED)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return  # Unresolvable: TM1py reports it as unreachable.
    for info in infos:
        if is_private_address(info[4][0]):
            raise TM1ConnectionError(PRIVATE_ADDRESS_REFUSED)


class TM1ConnectionManager:

    def __init__(self):
        self._clients: dict[uuid.UUID, TM1Service] = {}

    async def get_client(self, connection: TM1Connection) -> TM1Service:
        # Every use of a connection's credentials passes through here, so
        # this one check stops chat tools, monitors, deployments and
        # scheduled jobs alike — including a session opened before the
        # suspension, which is dropped rather than reused.
        if getattr(connection, "suspended_at", None) is not None:
            self.invalidate(connection.id)
            raise TM1ConnectionSuspendedError(
                "This TM1 connection has been suspended by the platform administrator."
            )

        if connection.id in self._clients:
            return self._clients[connection.id]

        client = await self._connect(connection)
        self._clients[connection.id] = client

        return client

    async def _connect(self, connection: TM1Connection) -> TM1Service:
        await _refuse_private_destination(connection)
        password = decrypt_password(connection.encrypted_password)

        return await call_with_resilience(
            connection.id,
            TM1Service,
            **build_tm1_kwargs(connection, password),
        )

    def invalidate(self, connection_id: uuid.UUID) -> None:
        client = self._clients.pop(connection_id, None)
        remove_circuit_breaker(connection_id)

        if client is not None:
            self._logout_in_background(client)

    @staticmethod
    def _logout_in_background(client: TM1Service) -> None:
        """End the TM1 session without making the caller wait for it.

        A dropped client used to keep its session open until TM1 timed
        it out; on a server with a session cap that is a seat held by
        nobody.
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _logout_quietly(client)
            return

        loop.run_in_executor(None, _logout_quietly, client)

    async def shutdown(self) -> None:
        """Log every cached session out. Called when the app stops."""

        clients = list(self._clients.values())
        self._clients.clear()

        for client in clients:
            await asyncio.to_thread(_logout_quietly, client)


tm1_connection_manager = TM1ConnectionManager()
