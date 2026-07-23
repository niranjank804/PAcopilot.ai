import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
from src.tm1.metadata.reference_parser import (
    extract_rule_cube_references,
    extract_ti_cube_writes,
)
from src.tm1.service import tm1_integration_service


class ExtractionSummary:

    def __init__(self, objects_created: int, relationships_created: int):
        self.objects_created = objects_created
        self.relationships_created = relationships_created


class _GraphWriter:
    """Accumulates nodes and edges for one extraction run, deduplicating
    objects by (type, name) and edges by (from, to, type)."""

    def __init__(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        extracted_at: datetime,
    ):
        self._db = db
        self._connection_id = connection_id
        self._organization_id = organization_id
        self._extracted_at = extracted_at
        self._objects: dict[tuple[str, str], TM1Object] = {}
        self._edges: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        self.relationships_created = 0

    @property
    def objects_created(self) -> int:
        return len(self._objects)

    def get_object(self, object_type: str, name: str) -> TM1Object | None:
        return self._objects.get((object_type, name))

    def list_names(self, object_type: str) -> list[str]:
        return [
            name
            for (existing_type, name) in self._objects
            if existing_type == object_type
        ]

    async def add_object(self, object_type: str, name: str) -> TM1Object:
        existing = self._objects.get((object_type, name))

        if existing is not None:
            return existing

        obj = await tm1_object_repository.create(
            self._db,
            TM1Object(
                connection_id=self._connection_id,
                organization_id=self._organization_id,
                object_type=object_type,
                name=name,
                extracted_at=self._extracted_at,
            ),
        )
        self._objects[(object_type, name)] = obj

        return obj

    async def add_relationship(
        self,
        from_object: TM1Object,
        to_object: TM1Object,
        relationship_type: str,
    ) -> None:
        key = (from_object.id, to_object.id, relationship_type)

        if key in self._edges:
            return

        await tm1_relationship_repository.create(
            self._db,
            TM1Relationship(
                connection_id=self._connection_id,
                organization_id=self._organization_id,
                from_object_id=from_object.id,
                to_object_id=to_object.id,
                relationship_type=relationship_type,
                extracted_at=self._extracted_at,
            ),
        )
        self._edges.add(key)
        self.relationships_created += 1


async def extract_metadata(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> ExtractionSummary:

    await tm1_relationship_repository.delete_by_connection(db, connection_id)
    await tm1_object_repository.delete_by_connection(db, connection_id)

    writer = _GraphWriter(
        db, connection_id, organization_id, datetime.now(timezone.utc)
    )

    # Cubes, dimensions, cube -> uses_dimension -> dimension
    cube_names = await tm1_integration_service.list_cubes(
        db, connection_id, organization_id
    )

    cubes_with_rules: list[str] = []

    for cube_name in cube_names:
        cube_info = await tm1_integration_service.get_cube(
            db, connection_id, organization_id, cube_name
        )

        cube_object = await writer.add_object("cube", cube_info.name)

        if cube_info.has_rules:
            cubes_with_rules.append(cube_info.name)

        for dimension_name in cube_info.dimensions:
            dimension_object = await writer.add_object("dimension", dimension_name)
            await writer.add_relationship(
                cube_object, dimension_object, "uses_dimension"
            )

    # Hierarchies: dimension -> contains_hierarchy -> hierarchy.
    # Hierarchy names are only unique per dimension, so nodes are stored
    # under the TM1 "Dimension:Hierarchy" qualified name.
    for dimension_name in writer.list_names("dimension"):
        dimension_object = writer.get_object("dimension", dimension_name)
        dimension_info = await tm1_integration_service.get_dimension(
            db, connection_id, organization_id, dimension_name
        )

        for hierarchy_name in dimension_info.hierarchy_names:
            hierarchy_object = await writer.add_object(
                "hierarchy", f"{dimension_name}:{hierarchy_name}"
            )
            await writer.add_relationship(
                dimension_object, hierarchy_object, "contains_hierarchy"
            )

    # Rules: cube -> references_cube -> cube (heuristic DB('...') scan;
    # self-references and cubes not in the model are skipped).
    for cube_name in cubes_with_rules:
        rule_text = await tm1_integration_service.get_cube_rules(
            db, connection_id, organization_id, cube_name
        )
        cube_object = writer.get_object("cube", cube_name)

        for referenced_name in extract_rule_cube_references(rule_text or ""):
            if referenced_name == cube_name:
                continue

            referenced_object = writer.get_object("cube", referenced_name)

            if referenced_object is not None:
                await writer.add_relationship(
                    cube_object, referenced_object, "references_cube"
                )

    # Processes: process -> reads_cube (structured TM1CubeView datasource)
    # and process -> updates_cube (heuristic CellPut/CellIncrement scan).
    process_names = await tm1_integration_service.list_processes(
        db, connection_id, organization_id
    )

    for process_name in process_names:
        process_info = await tm1_integration_service.get_process(
            db, connection_id, organization_id, process_name
        )

        process_object = await writer.add_object("process", process_info.name)

        if process_info.datasource_type == "TM1CubeView":
            source_cube = writer.get_object("cube", process_info.datasource_name)

            if source_cube is not None:
                await writer.add_relationship(
                    process_object, source_cube, "reads_cube"
                )

        all_code = "\n".join(
            (
                process_info.prolog,
                process_info.metadata,
                process_info.data,
                process_info.epilog,
            )
        )

        for written_name in extract_ti_cube_writes(all_code):
            written_cube = writer.get_object("cube", written_name)

            if written_cube is not None:
                await writer.add_relationship(
                    process_object, written_cube, "updates_cube"
                )

    # Chores: chore -> runs_process -> process (skips process names not
    # already in the graph, same "skip unknown reference" rule as
    # references_cube/updates_cube above).
    chore_names = await tm1_integration_service.list_chores(
        db, connection_id, organization_id
    )

    for chore_name in chore_names:
        chore_info = await tm1_integration_service.get_chore(
            db, connection_id, organization_id, chore_name
        )

        chore_object = await writer.add_object("chore", chore_info.name)

        for process_name in chore_info.process_names:
            process_object = writer.get_object("process", process_name)

            if process_object is not None:
                await writer.add_relationship(
                    chore_object, process_object, "runs_process"
                )

    return ExtractionSummary(
        objects_created=writer.objects_created,
        relationships_created=writer.relationships_created,
    )
