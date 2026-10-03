import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
from src.tm1.metadata.reference_parser import extract_rule_cube_references
from src.tm1.service import tm1_integration_service
from src.tm1.services import structure_service
from src.tm1.ti.parser import parse_process_code

# TI functions that change a dimension rather than look something up in it.
# DIMIX, ELPAR and friends are reads; these are writes.
DIMENSION_WRITE_FUNCTIONS = frozenset(
    {
        "DIMENSIONCREATE",
        "DIMENSIONDESTROY",
        "DIMENSIONDELETEALLELEMENTS",
        "DIMENSIONELEMENTINSERT",
        "DIMENSIONELEMENTDELETE",
        "DIMENSIONELEMENTCOMPONENTADD",
        "DIMENSIONELEMENTCOMPONENTDELETE",
        "ATTRPUTS",
        "ATTRPUTN",
        "ATTRINSERT",
        "ATTRDELETE",
    }
)

# Public views and subsets recorded per cube / dimension. Bounded because
# some models carry hundreds of user subsets on one dimension.
MAX_VIEWS_PER_CUBE = 50
MAX_SUBSETS_PER_DIMENSION = 50


class ExtractionSummary:

    def __init__(
        self,
        objects_created: int,
        relationships_created: int,
        unresolved_references: int = 0,
    ):
        self.objects_created = objects_created
        self.relationships_created = relationships_created
        # References whose object name is built from a variable. Not
        # recorded as edges — the object depends on runtime values — but
        # counted, so "no edge" is never mistaken for "no dependency".
        self.unresolved_references = unresolved_references


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

    # Views and subsets: view -> view_of_cube -> cube, subset ->
    # subset_of_dimension -> dimension. Public only; qualified names, since
    # a view name is only unique within its cube.
    connection, client = await tm1_integration_service.connect(
        db, connection_id, organization_id
    )

    # A listing TM1 security refuses (or a server that times out on one
    # object) costs that object's views or subsets, not the extraction.
    for cube_name in writer.list_names("cube"):
        try:
            views = await structure_service.list_views(client, connection.id, cube_name)
            public_views = [v for v in views["public"] if isinstance(v, str)]
        except Exception:  # noqa: BLE001
            continue

        cube_object = writer.get_object("cube", cube_name)

        for view_name in public_views[:MAX_VIEWS_PER_CUBE]:
            view_object = await writer.add_object("view", f"{cube_name}:{view_name}")
            await writer.add_relationship(view_object, cube_object, "view_of_cube")

    for dimension_name in writer.list_names("dimension"):
        try:
            subsets = [
                s
                for s in await structure_service.list_subsets(
                    client, connection.id, dimension_name, dimension_name
                )
                if isinstance(s, str)
            ]
        except Exception:  # noqa: BLE001
            continue

        dimension_object = writer.get_object("dimension", dimension_name)

        for subset_name in subsets[:MAX_SUBSETS_PER_DIMENSION]:
            subset_object = await writer.add_object(
                "subset", f"{dimension_name}:{subset_name}"
            )
            await writer.add_relationship(
                subset_object, dimension_object, "subset_of_dimension"
            )

    # Processes. Two passes: every process node first, so an ExecuteProcess
    # call to a process later in the list still finds its target. Which
    # edges a process makes: see process_edges below.
    process_names = await tm1_integration_service.list_processes(
        db, connection_id, organization_id
    )
    processes = []

    for process_name in process_names:
        process_info = await tm1_integration_service.get_process(
            db, connection_id, organization_id, process_name
        )
        await writer.add_object("process", process_info.name)
        processes.append(process_info)

    index = _GraphIndex(writer._objects)
    unresolved = 0

    for process_info in processes:
        process_object = writer.get_object("process", process_info.name)
        edges, missed = process_edges(process_info, index)
        unresolved += missed

        for target, relationship in edges:
            if target is not process_object:
                await writer.add_relationship(process_object, target, relationship)

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
        unresolved_references=unresolved,
    )


class _GraphIndex:
    """Find graph objects the way TI names them.

    TM1 names are case-insensitive, so code may not match the server's
    casing. Views and subsets are stored qualified ("Sales:Default") because
    a name is unique only within its cube or dimension, but TI names them by
    the short name with the container in another argument: a short name
    that matches exactly one public view or subset resolves; one that
    matches several, or none (a temporary view the process creates and
    destroys), does not.
    """

    def __init__(self, objects: dict[tuple[str, str], TM1Object]):
        self._objects = objects
        self._by_lower = {(t, n.lower()): (t, n) for (t, n) in objects}
        self._qualified: dict[str, dict[str, list[str]]] = {"view": {}, "subset": {}}
        for (kind, name) in objects:
            if kind in self._qualified:
                short = name.partition(":")[2].lower()
                self._qualified[kind].setdefault(short, []).append(name)

    def get(self, kind: str, name: str) -> TM1Object | None:
        return self._objects.get((kind, name))

    def lookup(self, kind: str, name: str) -> TM1Object | None:
        exact = self._objects.get((kind, name))
        if exact is not None:
            return exact
        key = self._by_lower.get((kind, name.lower()))
        return self._objects.get(key) if key else None

    def by_short_name(self, kind: str, short: str) -> TM1Object | None:
        matches = self._qualified[kind].get(short.lower(), [])
        return self._objects.get((kind, matches[0])) if len(matches) == 1 else None


def process_edges(process_info, index: _GraphIndex) -> tuple[list[tuple[TM1Object, str]], int]:
    """The edges one process makes, from its code, and how many references
    it makes through a variable (real dependencies the graph cannot draw).

    Edges come from the TI parser (src/tm1/ti/parser.py), the same one
    standards learning uses: reads_cube (CellGet*, or a TM1CubeView
    datasource), reads_view (that datasource's view), updates_cube
    (CellPut*/CellIncrement*), calls_process (ExecuteProcess/RunProcess),
    updates_dimension (element and attribute writes), references_dimension
    (lookups), and uses_view / uses_subset. Only literal names make edges.
    """

    record = parse_process_code(
        process_info.name,
        prolog=process_info.prolog,
        metadata=process_info.metadata,
        data=process_info.data,
        epilog=process_info.epilog,
        datasource_type=process_info.datasource_type,
        datasource_name=process_info.datasource_name,
    )
    edges: list[tuple[TM1Object, str]] = []
    unresolved = 0

    if process_info.datasource_type == "TM1CubeView":
        source_cube = index.lookup("cube", process_info.datasource_name)

        if source_cube is not None:
            edges.append((source_cube, "reads_cube"))

            if process_info.datasource_view:
                source_view = index.get(
                    "view", f"{source_cube.name}:{process_info.datasource_view}"
                )
                if source_view is not None:
                    edges.append((source_view, "reads_view"))

    for ref in record.objects:
        if not ref.literal:
            if ref.kind in ("cube", "dimension", "process"):
                unresolved += 1
            continue

        if ref.kind == "cube" and ref.access in ("write", "read"):
            target = index.lookup("cube", ref.name)
            relationship = "updates_cube" if ref.access == "write" else "reads_cube"
        elif ref.kind == "process" and ref.access == "calls":
            target = index.lookup("process", ref.name)
            relationship = "calls_process"
        elif ref.kind == "dimension":
            target = index.lookup("dimension", ref.name)
            relationship = (
                "updates_dimension"
                if ref.function in DIMENSION_WRITE_FUNCTIONS
                else "references_dimension"
            )
        elif ref.kind in ("view", "subset"):
            target = index.by_short_name(ref.kind, ref.name)
            relationship = f"uses_{ref.kind}"
        else:
            continue

        if target is not None:
            edges.append((target, relationship))

    return edges, unresolved


async def refresh_process(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    process_name: str,
    *,
    deleted: bool = False,
) -> bool:
    """Bring one process's place in the graph up to date after a change
    PA-Copilot applied to it, without re-reading the whole model.

    A no-op for a connection that has never been extracted. The process
    keeps the graph's extraction time, so the graph never claims to be
    fresher than its last full read. Returns whether the graph was touched.
    """

    objects = {
        (obj.object_type, obj.name): obj
        for obj in (
            await db.execute(
                select(TM1Object).where(TM1Object.connection_id == connection_id)
            )
        ).scalars()
    }
    if not objects:
        return False

    index = _GraphIndex(objects)
    existing = index.lookup("process", process_name)

    if existing is not None:
        await db.execute(
            delete(TM1Relationship).where(TM1Relationship.from_object_id == existing.id)
        )

    if deleted:
        if existing is not None:
            # Edges into it (chores, callers) go with it.
            await db.execute(
                delete(TM1Relationship).where(TM1Relationship.to_object_id == existing.id)
            )
            await db.delete(existing)
        return True

    process_info = await tm1_integration_service.get_process(
        db, connection_id, organization_id, process_name
    )
    extracted_at = max(obj.extracted_at for obj in objects.values())

    if existing is None:
        existing = await tm1_object_repository.create(
            db,
            TM1Object(
                connection_id=connection_id,
                organization_id=organization_id,
                object_type="process",
                name=process_info.name,
                extracted_at=extracted_at,
            ),
        )

    edges, _ = process_edges(process_info, index)
    seen = set()
    for target, relationship in edges:
        if target is existing or (target.id, relationship) in seen:
            continue
        seen.add((target.id, relationship))
        await tm1_relationship_repository.create(
            db,
            TM1Relationship(
                connection_id=connection_id,
                organization_id=organization_id,
                from_object_id=existing.id,
                to_object_id=target.id,
                relationship_type=relationship,
                extracted_at=extracted_at,
            ),
        )

    return True
