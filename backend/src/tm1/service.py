import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.database.models.tm1_connection import TM1Connection
from src.repositories.tm1_connection_repository import tm1_connection_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.crypto import encrypt_password
from src.tm1.exceptions import TM1AuthenticationError, TM1ConnectionError
from src.tm1.resilience import call_with_resilience
from src.tm1.services import (
    cell_service,
    chore_service,
    cube_service,
    dimension_service,
    process_service,
    security_service,
)
from src.tm1.services.cell_service import CellsetResult
from src.tm1.services.chore_service import ChoreInfo
from src.tm1.services.cube_service import CubeInfo
from src.tm1.services.dimension_service import DimensionInfo
from src.tm1.services.process_service import ProcessInfo
from src.tm1.services.security_service import GroupInfo


class TM1IntegrationService:

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
    ) -> TM1Connection:

        if authentication_type == "v12_saas" and not (tenant and database):
            raise ValidationException(
                "v12_saas connections require both 'tenant' and 'database'."
            )

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
        )

        return await tm1_connection_repository.create(db, connection)

    async def get_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> TM1Connection:

        connection = await tm1_connection_repository.get_by_id(db, connection_id)

        if connection is None or connection.organization_id != organization_id:
            raise NotFoundException("TM1 connection not found.")

        return connection

    async def list_connections(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[TM1Connection]:

        return await tm1_connection_repository.list_by_organization(
            db,
            organization_id,
        )

    async def delete_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        connection = await self.get_connection(db, connection_id, organization_id)

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
    ) -> TM1Connection:

        connection = await self.get_connection(db, connection_id, organization_id)

        next_auth_type = authentication_type or connection.authentication_type
        next_tenant = tenant if tenant is not None else connection.tenant
        next_database = database if database is not None else connection.database

        if next_auth_type == "v12_saas" and not (next_tenant and next_database):
            raise ValidationException(
                "v12_saas connections require both 'tenant' and 'database'."
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

        connection = await self.get_connection(db, connection_id, organization_id)

        try:
            client = await tm1_connection_manager.get_client(connection)

            await call_with_resilience(
                connection.id,
                client.server.get_server_name,
            )
        except (TM1ConnectionError, TM1AuthenticationError):
            tm1_connection_manager.invalidate(connection.id)

            return False

        return True

    async def list_cubes(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await cube_service.list_cubes(client, connection.id)

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
    ) -> list[str]:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await dimension_service.list_dimensions(client, connection.id)

    async def get_dimension(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        dimension_name: str,
    ) -> DimensionInfo:

        connection = await self.get_connection(db, connection_id, organization_id)
        client = await tm1_connection_manager.get_client(connection)

        return await dimension_service.get_dimension(
            client,
            connection.id,
            dimension_name,
        )

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


tm1_integration_service = TM1IntegrationService()
