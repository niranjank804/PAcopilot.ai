import time
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.models.tm1_connection import TM1Connection
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.core.exceptions import NotFoundException
from src.repositories.tm1_change_repository import tm1_change_repository
from src.schemas.tm1 import (
    ChangeCreate,
    ChangeDetailResponse,
    ChangeResponse,
    ChoreResponse,
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    CubeResponse,
    CubeRulesResponse,
    DependencyNode,
    DependencyPathResponse,
    DimensionResponse,
    ExtractionSummaryResponse,
    ObjectRelationshipsResponse,
    PathNode,
    ProcessResponse,
    SecurityGroupResponse,
    TestConnectionResponse,
    UnusedObject,
    VisualizeCell,
    VisualizeRequest,
    VisualizeResponse,
)
from src.ai.visualization import generate_visualization
from src.services.audit_service import audit_service
from src.tm1.deployment.change_service import change_service
from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.extractor import extract_metadata
from src.tm1.service import tm1_integration_service

router = APIRouter(
    prefix="/tm1",
    tags=["TM1"],
)


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


async def _log_tm1_access(
    db: AsyncSession,
    current_user: UserResponse,
    http_request: Request,
    *,
    action: str,
    connection: TM1Connection | None,
    elapsed_ms: int,
    extra: dict | None = None,
) -> None:
    ip_address, user_agent = _client_context(http_request)

    new_values = {
        "correlation_id": str(uuid.uuid4()),
        "elapsed_ms": elapsed_ms,
        "server": connection.address if connection else None,
    }

    if extra:
        new_values.update(extra)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=action,
        entity="TM1Connection",
        entity_id=connection.id if connection else None,
        new_values=new_values,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post(
    "/connections",
    response_model=ApiResponse[ConnectionResponse],
    status_code=201,
)
async def create_connection(
    request: ConnectionCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.create_connection(
        db,
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        name=request.name,
        address=request.address,
        port=request.port,
        ssl=request.ssl,
        username=request.username,
        password=request.password,
        authentication_type=request.authentication_type,
        tenant=request.tenant,
        database=request.database,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="create_connection",
        connection=connection,
        elapsed_ms=elapsed_ms,
    )

    return ApiResponse(
        success=True,
        data=ConnectionResponse.model_validate(connection),
    )


@router.get(
    "/connections",
    response_model=ApiResponse[list[ConnectionResponse]],
)
async def list_connections(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connections = await tm1_integration_service.list_connections(
        db,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_connections",
        connection=None,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(connections)},
    )

    return ApiResponse(
        success=True,
        data=[ConnectionResponse.model_validate(c) for c in connections],
    )


@router.get(
    "/connections/{connection_id}",
    response_model=ApiResponse[ConnectionResponse],
)
async def get_connection(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_connection",
        connection=connection,
        elapsed_ms=elapsed_ms,
    )

    return ApiResponse(
        success=True,
        data=ConnectionResponse.model_validate(connection),
    )


@router.patch(
    "/connections/{connection_id}",
    response_model=ApiResponse[ConnectionResponse],
)
async def update_connection(
    connection_id: uuid.UUID,
    request: ConnectionUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.update_connection(
        db,
        connection_id,
        current_user.organization_id,
        **request.model_dump(exclude_unset=True),
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="update_connection",
        connection=connection,
        elapsed_ms=elapsed_ms,
    )

    return ApiResponse(
        success=True,
        data=ConnectionResponse.model_validate(connection),
    )


@router.delete(
    "/connections/{connection_id}",
    response_model=ApiResponse[None],
)
async def delete_connection(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    await tm1_integration_service.delete_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="delete_connection",
        connection=connection,
        elapsed_ms=elapsed_ms,
    )

    return ApiResponse(success=True, data=None)


@router.post(
    "/connections/{connection_id}/test",
    response_model=ApiResponse[TestConnectionResponse],
)
async def test_connection(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    connected = await tm1_integration_service.test_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="test_connection",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"connected": connected},
    )

    return ApiResponse(success=True, data=TestConnectionResponse(connected=connected))


@router.get(
    "/connections/{connection_id}/cubes",
    response_model=ApiResponse[list[str]],
)
async def list_cubes(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    cubes = await tm1_integration_service.list_cubes(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_cubes",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(cubes)},
    )

    return ApiResponse(success=True, data=cubes)


@router.get(
    "/connections/{connection_id}/cubes/{cube_name}",
    response_model=ApiResponse[CubeResponse],
)
async def get_cube(
    connection_id: uuid.UUID,
    cube_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    cube = await tm1_integration_service.get_cube(
        db,
        connection_id,
        current_user.organization_id,
        cube_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_cube",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"cube": cube_name, "rows_returned": 1},
    )

    return ApiResponse(
        success=True,
        data=CubeResponse(
            name=cube.name,
            dimensions=cube.dimensions,
            has_rules=cube.has_rules,
        ),
    )


@router.get(
    "/connections/{connection_id}/dimensions",
    response_model=ApiResponse[list[str]],
)
async def list_dimensions(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    dimensions = await tm1_integration_service.list_dimensions(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_dimensions",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(dimensions)},
    )

    return ApiResponse(success=True, data=dimensions)


@router.get(
    "/connections/{connection_id}/dimensions/{dimension_name}",
    response_model=ApiResponse[DimensionResponse],
)
async def get_dimension(
    connection_id: uuid.UUID,
    dimension_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    dimension = await tm1_integration_service.get_dimension(
        db,
        connection_id,
        current_user.organization_id,
        dimension_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_dimension",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"dimension": dimension_name, "rows_returned": 1},
    )

    return ApiResponse(
        success=True,
        data=DimensionResponse(
            name=dimension.name,
            hierarchy_names=dimension.hierarchy_names,
        ),
    )


@router.post(
    "/connections/{connection_id}/visualize",
    response_model=ApiResponse[VisualizeResponse],
)
async def visualize(
    connection_id: uuid.UUID,
    request: VisualizeRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    result = await generate_visualization(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        connection_id=connection_id,
        query=request.query,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="visualize",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"cube": result.cube_name, "cell_count": len(result.cells)},
    )

    return ApiResponse(
        success=True,
        data=VisualizeResponse(
            cube_name=result.cube_name,
            mdx=result.mdx,
            summary=result.summary,
            cells=[
                VisualizeCell(label=label, value=value)
                for label, value in result.cells.items()
            ],
        ),
    )


@router.post(
    "/connections/{connection_id}/metadata/extract",
    response_model=ApiResponse[ExtractionSummaryResponse],
)
async def extract_connection_metadata(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    summary = await extract_metadata(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="extract_metadata",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "objects_created": summary.objects_created,
            "relationships_created": summary.relationships_created,
        },
    )

    return ApiResponse(
        success=True,
        data=ExtractionSummaryResponse(
            objects_created=summary.objects_created,
            relationships_created=summary.relationships_created,
        ),
    )


@router.get(
    "/connections/{connection_id}/metadata/cubes/{cube_name}/dependencies",
    response_model=ApiResponse[list[str]],
)
async def get_cube_dependencies(
    connection_id: uuid.UUID,
    cube_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    dimensions = await dependency_analyzer.get_cube_dependencies(
        db,
        connection_id,
        current_user.organization_id,
        cube_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_cube_dependencies",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"cube": cube_name, "rows_returned": len(dimensions)},
    )

    return ApiResponse(success=True, data=dimensions)


@router.get(
    "/connections/{connection_id}/metadata/dimensions/{dimension_name}/dependents",
    response_model=ApiResponse[list[str]],
)
async def get_dimension_dependents(
    connection_id: uuid.UUID,
    dimension_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    cubes = await dependency_analyzer.get_dimension_dependents(
        db,
        connection_id,
        current_user.organization_id,
        dimension_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_dimension_dependents",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"dimension": dimension_name, "rows_returned": len(cubes)},
    )

    return ApiResponse(success=True, data=cubes)


@router.get(
    "/connections/{connection_id}/processes",
    response_model=ApiResponse[list[str]],
)
async def list_processes(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    processes = await tm1_integration_service.list_processes(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_processes",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(processes)},
    )

    return ApiResponse(success=True, data=processes)


@router.get(
    "/connections/{connection_id}/processes/{process_name}",
    response_model=ApiResponse[ProcessResponse],
)
async def get_process(
    connection_id: uuid.UUID,
    process_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    process = await tm1_integration_service.get_process(
        db,
        connection_id,
        current_user.organization_id,
        process_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_process",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"process": process_name, "rows_returned": 1},
    )

    return ApiResponse(
        success=True,
        data=ProcessResponse(
            name=process.name,
            datasource_type=process.datasource_type,
            datasource_name=process.datasource_name,
            datasource_view=process.datasource_view,
            has_security_access=process.has_security_access,
            parameter_names=process.parameter_names,
            prolog=process.prolog,
            metadata=process.metadata,
            data=process.data,
            epilog=process.epilog,
        ),
    )


@router.get(
    "/connections/{connection_id}/chores",
    response_model=ApiResponse[list[str]],
)
async def list_chores(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    chores = await tm1_integration_service.list_chores(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_chores",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(chores)},
    )

    return ApiResponse(success=True, data=chores)


@router.get(
    "/connections/{connection_id}/chores/{chore_name}",
    response_model=ApiResponse[ChoreResponse],
)
async def get_chore(
    connection_id: uuid.UUID,
    chore_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    chore = await tm1_integration_service.get_chore(
        db,
        connection_id,
        current_user.organization_id,
        chore_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_chore",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"chore": chore_name, "rows_returned": 1},
    )

    return ApiResponse(
        success=True,
        data=ChoreResponse(
            name=chore.name,
            active=chore.active,
            process_names=chore.process_names,
        ),
    )


@router.get(
    "/connections/{connection_id}/cubes/{cube_name}/rules",
    response_model=ApiResponse[CubeRulesResponse],
)
async def get_cube_rules(
    connection_id: uuid.UUID,
    cube_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    rules = await tm1_integration_service.get_cube_rules(
        db,
        connection_id,
        current_user.organization_id,
        cube_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_cube_rules",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"cube": cube_name, "has_rules": rules is not None},
    )

    return ApiResponse(
        success=True,
        data=CubeRulesResponse(name=cube_name, rules=rules),
    )


@router.get(
    "/connections/{connection_id}/metadata/objects/{object_type}/{name}/relationships",
    response_model=ApiResponse[ObjectRelationshipsResponse],
)
async def get_object_relationships(
    connection_id: uuid.UUID,
    object_type: str,
    name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    relationships = await dependency_analyzer.get_object_relationships(
        db,
        connection_id,
        current_user.organization_id,
        object_type,
        name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_object_relationships",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "object_type": object_type,
            "object_name": name,
            "rows_returned": len(relationships["outgoing"])
            + len(relationships["incoming"]),
        },
    )

    return ApiResponse(
        success=True,
        data=ObjectRelationshipsResponse(**relationships),
    )


@router.get(
    "/connections/{connection_id}/metadata/objects/{object_type}/{name}/dependents",
    response_model=ApiResponse[list[DependencyNode]],
)
async def find_dependents(
    connection_id: uuid.UUID,
    object_type: str,
    name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
    max_depth: int = Query(default=10, ge=1, le=50),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    dependents = await dependency_analyzer.find_dependents(
        db,
        connection_id,
        current_user.organization_id,
        object_type,
        name,
        max_depth=max_depth,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="find_dependents",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "object_type": object_type,
            "object_name": name,
            "rows_returned": len(dependents),
        },
    )

    return ApiResponse(
        success=True,
        data=[DependencyNode(**entry) for entry in dependents],
    )


@router.get(
    "/connections/{connection_id}/metadata/objects/{object_type}/{name}/dependencies",
    response_model=ApiResponse[list[DependencyNode]],
)
async def find_dependencies(
    connection_id: uuid.UUID,
    object_type: str,
    name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
    max_depth: int = Query(default=10, ge=1, le=50),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    dependencies = await dependency_analyzer.find_dependencies(
        db,
        connection_id,
        current_user.organization_id,
        object_type,
        name,
        max_depth=max_depth,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="find_dependencies",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "object_type": object_type,
            "object_name": name,
            "rows_returned": len(dependencies),
        },
    )

    return ApiResponse(
        success=True,
        data=[DependencyNode(**entry) for entry in dependencies],
    )


@router.get(
    "/connections/{connection_id}/metadata/path",
    response_model=ApiResponse[DependencyPathResponse],
)
async def get_dependency_path(
    connection_id: uuid.UUID,
    http_request: Request,
    from_type: str,
    from_name: str,
    to_type: str,
    to_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
    max_depth: int = Query(default=10, ge=1, le=50),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    path = await dependency_analyzer.dependency_path(
        db,
        connection_id,
        current_user.organization_id,
        from_type,
        from_name,
        to_type,
        to_name,
        max_depth=max_depth,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="dependency_path",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "from": f"{from_type}:{from_name}",
            "to": f"{to_type}:{to_name}",
            "found": path is not None,
        },
    )

    return ApiResponse(
        success=True,
        data=DependencyPathResponse(
            found=path is not None,
            path=[PathNode(**entry) for entry in (path or [])],
        ),
    )


@router.get(
    "/connections/{connection_id}/metadata/unused",
    response_model=ApiResponse[list[UnusedObject]],
)
async def find_unused_objects(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
    object_type: str | None = None,
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    unused = await dependency_analyzer.find_unused_objects(
        db,
        connection_id,
        current_user.organization_id,
        object_type,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="find_unused_objects",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"object_type": object_type, "rows_returned": len(unused)},
    )

    return ApiResponse(
        success=True,
        data=[UnusedObject(**entry) for entry in unused],
    )


@router.get(
    "/connections/{connection_id}/security/groups",
    response_model=ApiResponse[list[str]],
)
async def list_security_groups(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.security.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    groups = await tm1_integration_service.list_security_groups(
        db,
        connection_id,
        current_user.organization_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="list_security_groups",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={"rows_returned": len(groups)},
    )

    return ApiResponse(success=True, data=groups)


@router.get(
    "/connections/{connection_id}/security/groups/{group_name}",
    response_model=ApiResponse[SecurityGroupResponse],
)
async def get_security_group(
    connection_id: uuid.UUID,
    group_name: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.security.read")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db,
        connection_id,
        current_user.organization_id,
    )

    group = await tm1_integration_service.get_security_group(
        db,
        connection_id,
        current_user.organization_id,
        group_name,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="get_security_group",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "group": group_name,
            "rows_returned": len(group.member_user_names),
        },
    )

    return ApiResponse(
        success=True,
        data=SecurityGroupResponse(
            name=group.name,
            member_user_names=group.member_user_names,
        ),
    )


@router.post(
    "/connections/{connection_id}/changes",
    response_model=ApiResponse[ChangeResponse],
    status_code=201,
)
async def create_change(
    connection_id: uuid.UUID,
    request: ChangeCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    start = time.monotonic()

    connection = await tm1_integration_service.get_connection(
        db, connection_id, current_user.organization_id
    )

    change = await change_service.create_change(
        db,
        connection_id=connection_id,
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        change_type=request.change_type,
        target_name=request.target_name,
        new_content=request.new_content,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="create_change",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "change_id": str(change.id),
            "change_type": change.change_type,
            "target": change.target_name,
        },
    )

    return ApiResponse(success=True, data=ChangeResponse.model_validate(change))


@router.get(
    "/connections/{connection_id}/changes",
    response_model=ApiResponse[list[ChangeResponse]],
)
async def list_changes(
    connection_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    await tm1_integration_service.get_connection(
        db, connection_id, current_user.organization_id
    )

    changes = await tm1_change_repository.list_by_connection(db, connection_id)

    return ApiResponse(
        success=True,
        data=[ChangeResponse.model_validate(c) for c in changes],
    )


async def _get_change_checked(
    db: AsyncSession,
    connection_id: uuid.UUID,
    change_id: uuid.UUID,
    organization_id: uuid.UUID,
):
    await tm1_integration_service.get_connection(db, connection_id, organization_id)

    change = await tm1_change_repository.get_by_id(db, change_id)

    if (
        change is None
        or change.connection_id != connection_id
        or change.organization_id != organization_id
    ):
        raise NotFoundException("Change not found.")

    return change


@router.get(
    "/connections/{connection_id}/changes/{change_id}",
    response_model=ApiResponse[ChangeDetailResponse],
)
async def get_change(
    connection_id: uuid.UUID,
    change_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    change = await _get_change_checked(
        db, connection_id, change_id, current_user.organization_id
    )

    preview = await change_service.get_change_preview(db, change)

    return ApiResponse(
        success=True,
        data=ChangeDetailResponse(
            change=ChangeResponse.model_validate(change),
            preview=preview,
        ),
    )


@router.post(
    "/connections/{connection_id}/changes/{change_id}/execute",
    response_model=ApiResponse[ChangeResponse],
)
async def execute_change(
    connection_id: uuid.UUID,
    change_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.deploy")),
):
    start = time.monotonic()

    change = await _get_change_checked(
        db, connection_id, change_id, current_user.organization_id
    )
    connection = await tm1_integration_service.get_connection(
        db, connection_id, current_user.organization_id
    )

    change = await change_service.execute_change(db, change, current_user.id)

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="execute_change",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "change_id": str(change.id),
            "change_type": change.change_type,
            "target": change.target_name,
            "result_status": change.status,
        },
    )

    return ApiResponse(success=True, data=ChangeResponse.model_validate(change))


@router.post(
    "/connections/{connection_id}/changes/{change_id}/rollback",
    response_model=ApiResponse[ChangeResponse],
)
async def rollback_change(
    connection_id: uuid.UUID,
    change_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.deploy")),
):
    start = time.monotonic()

    change = await _get_change_checked(
        db, connection_id, change_id, current_user.organization_id
    )
    connection = await tm1_integration_service.get_connection(
        db, connection_id, current_user.organization_id
    )

    change = await change_service.rollback_change(db, change)

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await _log_tm1_access(
        db,
        current_user,
        http_request,
        action="rollback_change",
        connection=connection,
        elapsed_ms=elapsed_ms,
        extra={
            "change_id": str(change.id),
            "change_type": change.change_type,
            "target": change.target_name,
        },
    )

    return ApiResponse(success=True, data=ChangeResponse.model_validate(change))
