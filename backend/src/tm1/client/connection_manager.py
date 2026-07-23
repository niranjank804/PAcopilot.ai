import uuid

from TM1py import TM1Service

from src.database.models.tm1_connection import TM1Connection
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
        return {
            "base_url": (
                f"https://{connection.address}/api/{connection.tenant}"
                f"/v0/tm1/{connection.database}/"
            ),
            "user": "apikey",
            "password": password,
            "ssl": True,
            "verify": True,
        }

    return {
        "address": connection.address,
        "port": connection.port,
        "ssl": connection.ssl,
        "user": connection.username,
        "password": password,
    }


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
        self._clients.pop(connection_id, None)
        remove_circuit_breaker(connection_id)


tm1_connection_manager = TM1ConnectionManager()
