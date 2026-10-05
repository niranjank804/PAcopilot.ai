import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import NotFoundException, ValidationException
from src.database.models.tm1_connection import TM1Connection
from src.repositories.auth_repository import auth_repository
from src.repositories.tm1_connection_repository import tm1_connection_repository
from src.tm1.addressing import (
    PRIVATE_ADDRESS_REFUSED,
    SAAS_NEEDS_SAAS_TYPE,
    is_private_address,
    is_saas_host,
    parse_address,
)
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.crypto import encrypt_password
from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1ConnectionError,
    TM1NotFoundError,
)
from src.tm1.resilience import call_with_resilience
from src.tm1.services import (
    cell_service,
    chore_service,
    cube_service,
    dimension_service,
    log_service,
    process_service,
    security_service,
    structure_service,
)
from src.tm1.services.cell_service import CellsetResult
from src.tm1.services.chore_service import ChoreInfo
from src.tm1.services.cube_service import CubeInfo
from src.tm1.services.dimension_service import DimensionInfo
from src.tm1.services.process_service import ProcessInfo
from src.tm1.services.security_service import GroupInfo


CREDENTIALS_REJECTED = "credentials_rejected"
NOT_FOUND = "not_found"
UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class ConnectionDiagnosis:
    connected: bool
    problem: str | None = None
    message: str | None = None


def _explain(problem: str, connection: TM1Connection, detail: str = "") -> str:
    saas = connection.authentication_type == "v12_saas"
    cloud = connection.authentication_type == "pa_cloud"

    if cloud:
        if problem == CREDENTIALS_REJECTED:
            return (
                f"IBM rejected the non-interactive account "
                f"'{connection.username}'. Check the account name and "
                "password exactly as IBM issued them, and that the account "
                f"has access to database '{connection.database}'."
            )
        if problem == NOT_FOUND:
            return (
                f"The server answered but database '{connection.database}' "
                "was not found. It is the TM1 server name shown in "
                "Planning Analytics Workspace, and it is case-sensitive."
            )
        return (
            f"Could not reach {connection.address}. Check the hostname — it "
            "ends in .planning-analytics.ibmcloud.com."
        )

    if problem == CREDENTIALS_REJECTED:
        if saas:
            return (
                f"IBM rejected the API key for tenant '{connection.tenant}'. "
                "Check the tenant ID, and that the API key was created in "
                "that tenant."
            )
        return "The server rejected the username or password."

    if problem == NOT_FOUND:
        if saas:
            return (
                f"The API key was accepted but database "
                f"'{connection.database}' was not found. Check the database "
                "name; it is case-sensitive."
            )
        return (
            "The server answered, but no TM1 REST API was found at this "
            "address and port."
        )

    if saas:
        return f"Could not reach {connection.address}. Check the hostname."
    if connection.gateway_id is not None:
        # "From the internet" is the wrong advice here: say what the
        # gateway reported, which names the fix.
        return (
            f"Could not reach {connection.address}:{connection.port} through "
            f"the gateway. {detail}"
        ).strip()
    return (
        f"Could not reach {connection.address}:{connection.port}. Check the "
        "address, port and SSL setting, and that the server accepts "
        "connections from the internet."
    )


def _check_pa_cloud(auth_type: str, database: str | None, username: str | None) -> None:
    if auth_type != "pa_cloud":
        return

    if not (database or "").strip():
        raise ValidationException(
            "A Planning Analytics on Cloud connection needs the database: "
            "the TM1 server name shown in Planning Analytics Workspace."
        )

    if not (username or "").strip() or username == "apikey":
        raise ValidationException(
            "A Planning Analytics on Cloud connection needs the "
            "non-interactive account name IBM issued."
        )


def _check_address_reachable_by_policy(address: str) -> None:
    if settings.TM1_ALLOW_PRIVATE_ADDRESSES:
        return

    if is_private_address(address):
        raise ValidationException(PRIVATE_ADDRESS_REFUSED)


# update_connection: "gateway_id not given", as distinct from None
# ("move this connection off its gateway").
_UNSET = object()


class TM1IntegrationService:

    async def _check_gateway(
        self,
        db: AsyncSession,
        gateway_id: uuid.UUID,
        organization_id: uuid.UUID,
        authentication_type: str,
    ) -> None:
        # Imported here: the gateway service imports models this module's
        # importers also load, and nothing else here needs it.
        from src.tm1.gateway.service import tm1_gateway_service

        if authentication_type != "native":
            raise ValidationException(
                "Only a Native (on-premises) connection can go through a "
                "gateway; Planning Analytics in IBM's cloud is reached directly."
            )
        # Raises NotFound for a gateway of another organization.
        await tm1_gateway_service.get(db, gateway_id, organization_id)

    async def create_connection(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        created_by: uuid.UUID,
        name: str,
        address: str,
        port: int,
        ssl: bool,
        username: str,
        password: str,
        authentication_type: str = "native",
        tenant: str | None = None,
        database: str | None = None,
        gateway_id: uuid.UUID | None = None,
        environment: str = "dev",
        visibility: str = "private",
    ) -> TM1Connection:

        parsed = parse_address(address)
        address = parsed.host
        tenant = tenant or parsed.tenant
        database = database or parsed.database

        if not address:
            raise ValidationException("Address is required.")

        # Through a gateway, the address is resolved inside the company's
        # network — a private address is the normal case, and the
        # gateway's own allow-list decides what it may reach.
        if gateway_id is not None:
            await self._check_gateway(db, gateway_id, organization_id, authentication_type)
        else:
            _check_address_reachable_by_policy(address)

        if is_saas_host(address) and authentication_type != "v12_saas":
            raise ValidationException(SAAS_NEEDS_SAAS_TYPE)

        if authentication_type == "v12_saas" and not (tenant and database):
            raise ValidationException(
                "v12_saas connections require both 'tenant' and 'database'."
            )

        _check_pa_cloud(authentication_type, database, username)

        connection = TM1Connection(
            organization_id=organization_id,
            created_by=created_by,
            name=name,
            address=address,
            port=port,
            ssl=ssl,
            username=username,
            encrypted_password=encrypt_password(password),
            authentication_type=authentication_type,
            tenant=tenant,
            database=database,
            gateway_id=gateway_id,
            environment=environment,
            # Owner: created_by, set from the session above, never from
            # the request body.
            visibility=visibility,
        )

        return await tm1_connection_repository.create(db, connection)

    async def _manages_all_connections(self, db: AsyncSession, user_id: uuid.UUID) -> bool:
        cached = db.info.get("manages_all_connections")
        if cached is not None and cached[0] == user_id:
            return cached[1]
        allowed = await auth_repository.user_has_permission(db, user_id, "tm1.connections.manage_all")
        db.info["manages_all_connections"] = (user_id, allowed)
        return allowed

    async def may_access(
        self,
        db: AsyncSession,
        connection: TM1Connection,
        *,
        purpose: str = "use",
        user_id: uuid.UUID | None = None,
    ) -> bool:
        """Whether the user may `use` this connection (anything that reads
        or changes TM1 through it, with its credentials) or `manage` it
        (see it in the list, edit, share or delete it).

        A shared connection: any member. A private one: its creator. An
        organization admin (tm1.connections.manage_all) may manage a
        private connection but not use it — seeing that a member has a
        server is administration; running queries with their credentials
        is not. No user (a scheduled job, a script) is the system.
        """

        user = user_id or db.info.get("user_id")
        if user is None:
            return True
        if connection.visibility == "organization" or connection.created_by == user:
            return True
        return purpose == "manage" and await self._manages_all_connections(db, user)

    async def get_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        purpose: str = "use",
        user_id: uuid.UUID | None = None,
    ) -> TM1Connection:

        connection = await tm1_connection_repository.get_by_id(db, connection_id)

        # Not found, another organization's, or another member's private
        # connection: the same answer, so its existence is not disclosed.
        if (
            connection is None
            or connection.organization_id != organization_id
            or not await self.may_access(db, connection, purpose=purpose, user_id=user_id)
        ):
            raise NotFoundException("TM1 connection not found.")

        return connection

    async def list_connections(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        purpose: str = "use",
    ) -> list[TM1Connection]:

        connections = await tm1_connection_repository.list_by_organization(
            db,
            organization_id,
        )
        return [
            c for c in connections
            if await self.may_access(db, c, purpose=purpose)
        ]

    async def delete_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        connection = await self.get_connection(
            db, connection_id, organization_id, purpose="manage"
        )

        tm1_connection_manager.invalidate(connection.id)

        await tm1_connection_repository.delete(db, connection)

    async def update_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        address: str | None = None,
        port: int | None = None,
        ssl: bool | None = None,
        username: str | None = None,
        password: str | None = None,
        authentication_type: str | None = None,
        tenant: str | None = None,
        database: str | None = None,
        gateway_id: object = _UNSET,
        environment: str | None = None,
        visibility: str | None = None,
    ) -> TM1Connection:

        connection = await self.get_connection(
            db, connection_id, organization_id, purpose="manage"
        )
        next_gateway = connection.gateway_id if gateway_id is _UNSET else gateway_id

        if address is not None:
            parsed = parse_address(address)
            address = parsed.host
            tenant = tenant or parsed.tenant
            database = database or parsed.database

            if not address:
                raise ValidationException("Address is required.")

            if next_gateway is None:
                _check_address_reachable_by_policy(address)

        next_address = address if address is not None else connection.address
        next_auth_type = authentication_type or connection.authentication_type
        next_tenant = tenant if tenant is not None else connection.tenant
        next_database = database if database is not None else connection.database

        if is_saas_host(next_address) and next_auth_type != "v12_saas":
            raise ValidationException(SAAS_NEEDS_SAAS_TYPE)

        if next_auth_type == "v12_saas" and not (next_tenant and next_database):
            raise ValidationException(
                "v12_saas connections require both 'tenant' and 'database'."
            )

        _check_pa_cloud(
            next_auth_type,
            next_database,
            username if username is not None else connection.username,
        )

        if name is not None:
            connection.name = name
        if address is not None:
            connection.address = address
        if port is not None:
            connection.port = port
        if ssl is not None:
            connection.ssl = ssl
        if username is not None:
            connection.username = username
        if password:
            connection.encrypted_password = encrypt_password(password)
        if authentication_type is not None:
            connection.authentication_type = authentication_type
        if tenant is not None:
            connection.tenant = tenant
        if database is not None:
            connection.database = database
        if environment is not None:
            connection.environment = environment
        if visibility is not None:
            connection.visibility = visibility
        if gateway_id is not _UNSET:
            if gateway_id is None:
                # Off the gateway: the address must now be reachable directly.
                _check_address_reachable_by_policy(connection.address)
            else:
                await self._check_gateway(
                    db, gateway_id, organization_id, connection.authentication_type
                )
            connection.gateway_id = gateway_id

        # Credentials or endpoint may have changed — never reuse a stale
        # cached TM1py client against the new configuration.
        tm1_connection_manager.invalidate(connection.id)

        return await tm1_connection_repository.update(db, connection)

    async def test_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> bool:

        diagnosis = await self.diagnose_connection(db, connection_id, organization_id)

        return diagnosis.connected

    async def diagnose_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ConnectionDiagnosis:
        """Try the connection and say which part is wrong if it fails.

        "Could not connect" alone sent a user round in circles: a wrong
        tenant, a wrong database name and an unreachable host all looked
        identical. The status TM1 answers with tells them apart.
        """

        connection = await self.get_connection(db, connection_id, organization_id)
        detail = ""

        try:
            client = await tm1_connection_manager.get_client(connection)

            await call_with_resilience(
                connection.id,
                client.server.get_server_name,
            )
        except TM1AuthenticationError:
            problem = CREDENTIALS_REJECTED
        except TM1NotFoundError:
            problem = NOT_FOUND
        except TM1ConnectionError as exc:
            problem = UNREACHABLE
            detail = exc.message
        else:
            return ConnectionDiagnosis(connected=True)

        tm1_connection_manager.invalidate(connection.id)

        return ConnectionDiagnosis(
            connected=False,
            problem=problem,
            message=_explain(problem, connection, detail),
        )

    async def run(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        operation,
        *args,
        **kwargs,
    ):
        """Resolve the connection *within the caller's organization*, then
        call `operation(client, connection.id, *args, **kwargs)`.

        The one place a service function meets a live client. Every
        operation reached through here inherits the same organization
        check, the connection's circuit breaker and TM1py's timeout,
        which is why new capabilities use this rather than adding one
        more near-identical wrapper method to this class.
        """

        connection, client = await self._client_for(db, connection_id, organization_id)

        return await operation(client, connection.id, *args, **kwargs)

    async def list_cubes(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        include_control: bool = False,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.list_cubes(
            client, connection.id, include_control=include_control
        )

    async def get_cube(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        cube_name: str,
    ) -> CubeInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.get_cube(client, connection.id, cube_name)

    async def list_dimensions(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        include_control: bool = False,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await dimension_service.list_dimensions(
            client, connection.id, include_control=include_control
        )

    async def get_dimension(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        *,
        with_counts: bool = False,
    ) -> DimensionInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        dimension = await dimension_service.get_dimension(
            client,
            connection.id,
            dimension_name,
        )
        if with_counts:
            dimension.element_counts = await dimension_service.count_elements(
                client, connection.id, dimension.name, dimension.hierarchy_names
            )
        return dimension

    async def get_cube_rules(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        cube_name: str,
    ) -> str | None:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.get_cube_rules(client, connection.id, cube_name)

    async def list_processes(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await process_service.list_processes(client, connection.id)

    async def get_process(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        process_name: str,
    ) -> ProcessInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await process_service.get_process(
            client,
            connection.id,
            process_name,
        )

    async def list_chores(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await chore_service.list_chores(client, connection.id)

    async def get_chore(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        chore_name: str,
    ) -> ChoreInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await chore_service.get_chore(
            client,
            connection.id,
            chore_name,
        )

    async def list_dimension_elements(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str | None = None,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await dimension_service.list_elements(
            client,
            connection.id,
            dimension_name,
            hierarchy_name,
        )

    async def execute_mdx(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        mdx: str,
    ) -> CellsetResult:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cell_service.execute_mdx(client, connection.id, mdx)

    async def list_security_groups(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await security_service.list_groups(client, connection.id)

    async def get_security_group(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        group_name: str,
    ) -> GroupInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await security_service.get_group(
            client,
            connection.id,
            group_name,
        )

    async def _client_for(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ):
        connection = await self.get_connection(db, connection_id, organization_id)
        return connection, await tm1_connection_manager.get_client(connection)

    async def connect(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ):
        """(connection, client) for a caller about to make several TM1
        calls concurrently.

        Resolve once, then fan out on the client. Fanning out through the
        methods above instead runs several queries on one AsyncSession at
        the same time, which SQLAlchemy does not permit — it works in a
        fast test and fails under a real driver.
        """

        return await self._client_for(db, connection_id, organization_id)

    async def list_views(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        cube_name: str,
    ) -> dict:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.list_views(client, connection.id, cube_name)

    async def list_hierarchies(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
    ) -> list[str]:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.list_hierarchies(
            client, connection.id, dimension_name
        )

    async def get_default_member(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str,
    ) -> str | None:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.get_default_member(
            client, connection.id, dimension_name, hierarchy_name
        )

    async def list_subsets(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str,
    ) -> list[str]:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.list_subsets(
            client, connection.id, dimension_name, hierarchy_name
        )

    async def get_attribute_definitions(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str,
    ) -> list[dict]:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.get_attribute_definitions(
            client, connection.id, dimension_name, hierarchy_name
        )

    async def get_element_parents(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str,
        element_name: str,
    ) -> list[str]:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.get_parents(
            client, connection.id, dimension_name, hierarchy_name, element_name
        )

    async def get_leaves_under(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
        hierarchy_name: str,
        consolidation: str,
    ) -> list[str]:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.get_leaves_under(
            client, connection.id, dimension_name, hierarchy_name, consolidation
        )

    async def get_server_state(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> dict:

        connection, client = await self._client_for(db, connection_id, organization_id)
        return await structure_service.get_server_state(client, connection.id)

    async def list_cubes_with_rules(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.list_cubes_with_rules(client, connection.id)

    async def search_rule_substring(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        substring: str,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.search_rule_substring(
            client, connection.id, substring
        )

    async def search_process_code(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        search_string: str,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await process_service.search_process_code(
            client,
            connection.id,
            search_string,
        )

    async def get_message_log(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        top: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        level: str | None = None,
        logger: str | None = None,
    ) -> list[dict]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await log_service.get_message_log(
            client,
            connection.id,
            top=top,
            since=since,
            until=until,
            level=level,
            logger=logger,
        )

    async def get_transaction_log(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        cube: str | None = None,
        user: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        top: int | None = None,
    ) -> list[dict]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await log_service.get_transaction_log(
            client,
            connection.id,
            cube=cube,
            user=user,
            since=since,
            until=until,
            top=top,
        )

    async def list_process_error_logs(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        process_name: str | None = None,
        top: int | None = None,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await log_service.list_process_error_logs(
            client,
            connection.id,
            process_name=process_name,
            top=top,
        )

    async def get_process_error_log(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        file_name: str,
    ) -> str:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await log_service.get_process_error_log(
            client,
            connection.id,
            file_name,
        )


tm1_integration_service = TM1IntegrationService()
