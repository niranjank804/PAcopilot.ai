import uuid
from collections import deque

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException
from src.database.models.tm1_object import TM1Object
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository

# Safety cap on nodes visited during a traversal, independent of max_depth —
# same "bounded so a pathological graph can't hang the request" discipline
# as MAX_TOOL_ROUNDS in the AI orchestrator's tool loop.
MAX_TRAVERSAL_NODES = 1000


async def get_cube_dependencies(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    cube_name: str,
) -> list[str]:

    cube_object = await tm1_object_repository.get_by_name(
        db, connection_id, "cube", cube_name
    )

    if cube_object is None or cube_object.organization_id != organization_id:
        raise NotFoundException(
            f"Cube '{cube_name}' not found in the metadata graph. "
            "Run metadata extraction for this connection first."
        )

    relationships = await tm1_relationship_repository.list_by_from_object(
        db, cube_object.id, "uses_dimension"
    )

    names = []

    for relationship in relationships:
        dimension_object = await tm1_object_repository.get_by_id(
            db, relationship.to_object_id
        )

        if dimension_object is not None:
            names.append(dimension_object.name)

    return names


async def get_dimension_dependents(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    dimension_name: str,
) -> list[str]:

    dimension_object = await tm1_object_repository.get_by_name(
        db, connection_id, "dimension", dimension_name
    )

    if (
        dimension_object is None
        or dimension_object.organization_id != organization_id
    ):
        raise NotFoundException(
            f"Dimension '{dimension_name}' not found in the metadata graph. "
            "Run metadata extraction for this connection first."
        )

    relationships = await tm1_relationship_repository.list_by_to_object(
        db, dimension_object.id, "uses_dimension"
    )

    names = []

    for relationship in relationships:
        cube_object = await tm1_object_repository.get_by_id(
            db, relationship.from_object_id
        )

        if cube_object is not None:
            names.append(cube_object.name)

    return names


async def get_object_relationships(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str,
    name: str,
) -> dict:

    obj = await tm1_object_repository.get_by_name(db, connection_id, object_type, name)

    if obj is None or obj.organization_id != organization_id:
        raise NotFoundException(
            f"{object_type.capitalize()} '{name}' not found in the metadata "
            "graph. Run metadata extraction for this connection first."
        )

    async def _related(relationships, other_id_attr):
        entries = []

        for relationship in relationships:
            other = await tm1_object_repository.get_by_id(
                db, getattr(relationship, other_id_attr)
            )

            if other is not None:
                entries.append(
                    {
                        "relationship_type": relationship.relationship_type,
                        "object_type": other.object_type,
                        "name": other.name,
                    }
                )

        return entries

    outgoing = await _related(
        await tm1_relationship_repository.list_by_from_object(db, obj.id),
        "to_object_id",
    )
    incoming = await _related(
        await tm1_relationship_repository.list_by_to_object(db, obj.id),
        "from_object_id",
    )

    return {
        "object_type": obj.object_type,
        "name": obj.name,
        "outgoing": outgoing,
        "incoming": incoming,
    }


async def _resolve_object(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str,
    name: str,
) -> TM1Object:

    obj = await tm1_object_repository.get_by_name(db, connection_id, object_type, name)

    if obj is None or obj.organization_id != organization_id:
        raise NotFoundException(
            f"{object_type.capitalize()} '{name}' not found in the metadata "
            "graph. Run metadata extraction for this connection first."
        )

    return obj


async def _traverse(
    db: AsyncSession,
    start: TM1Object,
    *,
    direction: str,
    max_depth: int,
) -> list[dict]:
    """BFS from `start`, walking incoming or outgoing edges. Bounded by
    max_depth and MAX_TRAVERSAL_NODES; a `visited` set makes this safe
    against cycles (e.g. two cubes referencing each other's rules)."""

    visited = {start.id}
    queue: deque[tuple[TM1Object, int]] = deque([(start, 0)])
    results: list[dict] = []

    while queue and len(visited) < MAX_TRAVERSAL_NODES:
        current, depth = queue.popleft()

        if depth >= max_depth:
            continue

        if direction == "incoming":
            relationships = await tm1_relationship_repository.list_by_to_object(
                db, current.id
            )
            neighbor_id_attr = "from_object_id"
        else:
            relationships = await tm1_relationship_repository.list_by_from_object(
                db, current.id
            )
            neighbor_id_attr = "to_object_id"

        for relationship in relationships:
            neighbor_id = getattr(relationship, neighbor_id_attr)

            if neighbor_id in visited:
                continue

            neighbor = await tm1_object_repository.get_by_id(db, neighbor_id)

            if neighbor is None:
                continue

            visited.add(neighbor_id)
            results.append(
                {
                    "object_type": neighbor.object_type,
                    "name": neighbor.name,
                    "relationship_type": relationship.relationship_type,
                    "via": current.name,
                    "depth": depth + 1,
                }
            )
            queue.append((neighbor, depth + 1))

    return results


async def find_dependents(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str,
    name: str,
    max_depth: int = 10,
) -> list[dict]:
    """Everything that transitively depends on this object (walks incoming
    edges) — e.g. "which chores eventually run because of this process"."""

    start = await _resolve_object(db, connection_id, organization_id, object_type, name)

    return await _traverse(db, start, direction="incoming", max_depth=max_depth)


async def find_dependencies(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str,
    name: str,
    max_depth: int = 10,
) -> list[dict]:
    """Everything this object transitively depends on (walks outgoing
    edges) — e.g. "show everything downstream of this process"."""

    start = await _resolve_object(db, connection_id, organization_id, object_type, name)

    return await _traverse(db, start, direction="outgoing", max_depth=max_depth)


async def dependency_path(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    from_type: str,
    from_name: str,
    to_type: str,
    to_name: str,
    max_depth: int = 10,
) -> list[dict] | None:
    """Shortest path from the source object to the target object, following
    outgoing edges. Returns None if no path exists within max_depth."""

    start = await _resolve_object(
        db, connection_id, organization_id, from_type, from_name
    )
    target = await _resolve_object(db, connection_id, organization_id, to_type, to_name)

    def _as_entry(obj: TM1Object) -> dict:
        return {"object_type": obj.object_type, "name": obj.name}

    if start.id == target.id:
        return [_as_entry(start)]

    parents: dict[uuid.UUID, TM1Object | None] = {start.id: None}
    queue: deque[tuple[TM1Object, int]] = deque([(start, 0)])

    while queue and len(parents) < MAX_TRAVERSAL_NODES:
        current, depth = queue.popleft()

        if depth >= max_depth:
            continue

        relationships = await tm1_relationship_repository.list_by_from_object(
            db, current.id
        )

        for relationship in relationships:
            neighbor_id = relationship.to_object_id

            if neighbor_id in parents:
                continue

            neighbor = await tm1_object_repository.get_by_id(db, neighbor_id)

            if neighbor is None:
                continue

            parents[neighbor_id] = current

            if neighbor_id == target.id:
                path = [neighbor]
                node: TM1Object | None = current

                while node is not None:
                    path.append(node)
                    node = parents[node.id]

                path.reverse()

                return [_as_entry(obj) for obj in path]

            queue.append((neighbor, depth + 1))

    return None


async def find_unused_objects(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str | None = None,
) -> list[dict]:
    """Objects that appear in zero relationships (neither side of any
    edge) — orphan cubes, unused dimensions, processes nothing runs,
    chores that reference nothing live."""

    objects = await tm1_object_repository.list_by_connection(
        db, connection_id, object_type
    )
    objects = [obj for obj in objects if obj.organization_id == organization_id]

    relationships = await tm1_relationship_repository.list_by_connection(
        db, connection_id
    )

    referenced_ids: set[uuid.UUID] = set()

    for relationship in relationships:
        referenced_ids.add(relationship.from_object_id)
        referenced_ids.add(relationship.to_object_id)

    return [
        {"object_type": obj.object_type, "name": obj.name}
        for obj in objects
        if obj.id not in referenced_ids
    ]
