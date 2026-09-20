import asyncio
import uuid

from TM1py import TM1Service

from src.core.config import settings
from src.database.models.tm1_connection import TM1Connection
from src.tm1.addressing import parse_address
from src.tm1.crypto import decrypt_password
from src.tm1.resilience import call_with_resilience, remove_circuit_breaker


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

    return {
        "address": connection.address,
        "port": connection.port,
        "ssl": connection.ssl,
        "user": connection.username,
        "password": password,
        **_timeout_kwargs(),
    }


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


class TM1ConnectionManager:

    def __init__(self):
        self._clients: dict[uuid.UUID, TM1Service] = {}

    async def get_client(self, connection: TM1Connection) -> TM1Service:
        if connection.id in self._clients:
            return self._clients[connection.id]

        client = await self._connect(connection)
        self._clients[connection.id] = client

        return client

    async def _connect(self, connection: TM1Connection) -> TM1Service:
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
