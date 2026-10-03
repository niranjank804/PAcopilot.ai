"""Find objects and follow what references what.

These answer the questions a TM1 developer asks before touching anything:
"is there already a cube called something like X", "what does this process
read and write", "what does it call, and what do those call", "what feeds
this cube and what reads from it".

Process references come from the TI parser (`tm1/ti/parser.py`) run over
the process source read live from TM1 — deterministic, with the section
each reference sits in. A reference built from a variable (CellPutN on
`sCube`) cannot be resolved statically; it is reported as unresolved, never
guessed.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.tm1._common import (
    CONNECTION_ID_SCHEMA,
    TM1Tool,
    connection_id_of,
    evidence,
    required_text,
)
from src.core.exceptions import NotFoundException
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
from src.tm1.exceptions import TM1NotFoundError
from src.tm1.metadata.reference_parser import extract_rule_cube_references
from src.tm1.service import tm1_integration_service
from src.tm1.services import (
    chore_service,
    cube_service,
    dimension_service,
    process_service,
    structure_service,
)
from src.tm1.ti.parser import ProcessRecord, parse_process_code

MAX_MATCHES_PER_TYPE = 50
MAX_TREE_NODES = 40
MAX_TREE_DEPTH = 6
MAX_FLOW_PROCESSES = 40
MAX_FLOW_CHORES = 60
CONCURRENCY = 5

SEARCHABLE_TYPES = ("cube", "dimension", "process", "chore", "element", "view", "subset")


def record_from(process) -> ProcessRecord:
    """A live `ProcessInfo` as a parsed record."""

    return parse_process_code(
        process.name,
        prolog=process.prolog,
        metadata=process.metadata,
        data=process.data,
        epilog=process.epilog,
        datasource_type=process.datasource_type,
        datasource_name=process.datasource_name,
        parameters=getattr(process, "parameters", None)
        or [{"name": n} for n in (process.parameter_names or [])],
        variables=getattr(process, "variables", None),
    )


def references_of(record: ProcessRecord) -> dict:
    """What a process touches, grouped, with where in the code."""

    grouped: dict[str, list[dict]] = {}
    unresolved: list[dict] = []
    seen: set[tuple] = set()

    for ref in record.objects:
        key = (ref.kind, ref.name, ref.access, ref.section, ref.literal)
        if key in seen:
            continue
        seen.add(key)

        entry = {"name": ref.name, "access": ref.access, "section": ref.section}

        if not ref.literal:
            unresolved.append({**entry, "kind": ref.kind})
            continue

        grouped.setdefault(ref.kind, []).append(entry)

    # A datasource view is a read the code never names.
    if record.datasource_type in ("tm1cubeview", "view") and record.datasource_name:
        grouped.setdefault("cube", []).append(
            {"name": record.datasource_name, "access": "read", "section": "datasource"}
        )

    return {"objects": grouped, "unresolved": unresolved}


def _match(names: list[str], query: str) -> list[str]:
    needle = query.lower().replace(" ", "")
    return [n for n in names if needle in n.lower().replace(" ", "")]


class SearchModelObjectsTool(TM1Tool):

    name = "search_model_objects"
    description = (
        "Find TM1 objects by partial name: cubes, dimensions, processes and "
        "chores across the model, elements within a dimension, views within "
        "a cube, subsets within a dimension. Case- and space-insensitive. "
        "Use this whenever the user names something approximately ('the "
        "workforce cube', 'a load process for FX') before calling a tool "
        "that needs the exact name. Element search runs on the server, so "
        "it works on very large dimensions."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "query": {"type": "string", "description": "Part of the name to find."},
            "object_types": {
                "type": "array",
                "items": {"type": "string", "enum": list(SEARCHABLE_TYPES)},
                "description": (
                    "Types to search. Default: cube, dimension, process, chore. "
                    "element and subset need dimension_name; view needs cube_name."
                ),
            },
            "dimension_name": {
                "type": "string",
                "description": "Dimension to search elements or subsets in.",
            },
            "hierarchy_name": {
                "type": "string",
                "description": "Hierarchy for element/subset search. Defaults to the dimension.",
            },
            "cube_name": {"type": "string", "description": "Cube to search views in."},
            "include_control": {
                "type": "boolean",
                "description": "Include control cubes and dimensions (names starting with '}').",
            },
        },
        "required": ["connection_id", "query"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        query = required_text(kwargs, "query")
        types = [t for t in (kwargs.get("object_types") or []) if t in SEARCHABLE_TYPES]
        types = types or ["cube", "dimension", "process", "chore"]
        dimension = str(kwargs.get("dimension_name") or "").strip()
        hierarchy = str(kwargs.get("hierarchy_name") or dimension).strip()
        cube = str(kwargs.get("cube_name") or "").strip()
        include_control = bool(kwargs.get("include_control"))

        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )
        cid = connection.id
        results: list[dict] = []
        counts: dict[str, int] = {}
        notes: list[str] = []

        async def names_of(kind: str) -> list[str]:
            if kind == "cube":
                return await cube_service.list_cubes(client, cid, include_control=include_control)
            if kind == "dimension":
                return await dimension_service.list_dimensions(
                    client, cid, include_control=include_control
                )
            if kind == "process":
                return await process_service.list_processes(client, cid)
            if kind == "chore":
                return await chore_service.list_chores(client, cid)
            if kind == "element":
                return await structure_service.search_elements(
                    client, cid, dimension, hierarchy, query
                )
            if kind == "view":
                views = await structure_service.list_views(client, cid, cube)
                return list(views["public"]) + [f"{v} (private)" for v in views["private"]]
            if kind == "subset":
                return await structure_service.list_subsets(client, cid, dimension, hierarchy)
            return []

        for kind in types:
            if kind in ("element", "subset") and not dimension:
                notes.append(f"{kind} search needs dimension_name; skipped.")
                continue
            if kind == "view" and not cube:
                notes.append("view search needs cube_name; skipped.")
                continue

            try:
                names = await names_of(kind)
            except TM1NotFoundError:
                notes.append(f"{kind}: the container named was not found.")
                continue

            # Elements were already filtered on the server.
            matched = names if kind == "element" else _match(names, query)
            counts[kind] = len(matched)
            parent = dimension if kind in ("element", "subset") else cube if kind == "view" else None

            for name in matched[:MAX_MATCHES_PER_TYPE]:
                results.append({"type": kind, "name": name, "in": parent})

            if len(matched) > MAX_MATCHES_PER_TYPE:
                notes.append(f"{kind}: first {MAX_MATCHES_PER_TYPE} of {len(matched)} shown.")

        return json.dumps(
            {
                "query": query,
                "counts": counts,
                "results": results,
                "notes": notes,
                "evidence": evidence(verified=["Object names read live from TM1 REST"]),
            }
        )


class AnalyzeProcessReferencesTool(TM1Tool):

    name = "analyze_process_references"
    description = (
        "Show everything one TurboIntegrator process touches — cubes it "
        "reads and writes, dimensions, views, subsets, attributes, and the "
        "processes it calls — with the code section of each reference. "
        "Parsed from the live process source, so it needs no metadata "
        "extraction. References built from variables are listed as "
        "unresolved rather than guessed."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {"type": "string", "description": "The process."},
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        name = required_text(kwargs, "process_name")
        process = await tm1_integration_service.get_process(
            db, connection_id_of(kwargs), organization_id, name
        )
        record = record_from(process)
        refs = references_of(record)

        return json.dumps(
            {
                "process": process.name,
                "datasource": {"type": process.datasource_type, "name": process.datasource_name},
                "parameters": getattr(process, "parameters", None) or process.parameter_names,
                **refs,
                "evidence": evidence(
                    verified=[
                        "Process source read live from TM1 REST",
                        "References extracted by the TI parser from that source",
                    ],
                    unknown=(
                        [
                            f"{len(refs['unresolved'])} reference(s) use a variable "
                            "for the object name; the object depends on runtime values"
                        ]
                        if refs["unresolved"]
                        else []
                    ),
                ),
            }
        )


class GetProcessCallTreeTool(TM1Tool):

    name = "get_process_call_tree"
    description = (
        "Walk the ExecuteProcess / RunProcess calls from one process "
        "downwards: which processes it calls, what those call, and so on, "
        "each with the cubes it writes. Reports processes that are called "
        "but do not exist, calls whose target is a variable, and cycles. "
        "Use this before changing a process that others depend on, or to "
        "understand an orchestration process."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {"type": "string", "description": "The root process."},
            "max_depth": {
                "type": "integer",
                "description": f"Levels to follow (default 4, at most {MAX_TREE_DEPTH}).",
            },
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        root = required_text(kwargs, "process_name")
        try:
            max_depth = int(kwargs.get("max_depth") or 4)
        except (TypeError, ValueError):
            max_depth = 4
        max_depth = max(1, min(max_depth, MAX_TREE_DEPTH))

        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )

        nodes: dict[str, dict] = {}
        # Each entry carries its call path, so a cycle is a callee that is
        # already an ancestor — not merely a process reached twice (a
        # diamond, which is ordinary).
        frontier: list[tuple[str, int, tuple[str, ...]]] = [(root, 0, ())]
        cycles: list[str] = []
        truncated = False

        while frontier:
            name, depth, path = frontier.pop(0)
            key = name.lower()

            if key in nodes:
                continue

            if len(nodes) >= MAX_TREE_NODES:
                truncated = True
                break

            try:
                process = await process_service.get_process(client, connection.id, name)
            except TM1NotFoundError:
                nodes[key] = {"name": name, "depth": depth, "exists": False, "calls": []}
                continue

            record = record_from(process)
            calls = sorted(record.processes_called, key=str.lower)
            dynamic = sorted(
                {o.name for o in record.objects if o.kind == "process" and not o.literal}
            )

            nodes[key] = {
                "name": process.name,
                "depth": depth,
                "exists": True,
                "calls": calls,
                "dynamic_calls": dynamic,
                "cubes_written": sorted(record.cubes_written),
            }

            here = path + (key,)

            for callee in calls:
                if callee.lower() in here:
                    cycles.append(f"{process.name} → {callee}")
                elif depth + 1 <= max_depth:
                    frontier.append((callee, depth + 1, here))

        missing = [n["name"] for n in nodes.values() if not n["exists"]]
        dynamic_total = sum(len(n.get("dynamic_calls", [])) for n in nodes.values())

        if missing and nodes.get(root.lower(), {}).get("exists") is False:
            raise NotFoundException(f"Process '{root}' was not found on this server.")

        return json.dumps(
            {
                "root": root,
                "max_depth": max_depth,
                "nodes": list(nodes.values()),
                "missing_processes": missing,
                "cycles": cycles,
                "truncated": truncated,
                "evidence": evidence(
                    verified=["Each process's source read live and parsed for ExecuteProcess / RunProcess"],
                    unknown=(
                        [f"{dynamic_total} call(s) name the target with a variable; those branches are not followed"]
                        if dynamic_total
                        else []
                    )
                    + ([f"Stopped at {MAX_TREE_NODES} processes"] if truncated else []),
                ),
            }
        )


class GetCubeDataFlowTool(TM1Tool):

    name = "get_cube_data_flow"
    description = (
        "Answer 'what writes to this cube, and what reads from it': the "
        "processes that write it (CellPut/CellIncrement), the processes "
        "that read it (CellGet or a cube-view datasource), the chores that "
        "run the writers, and the cubes whose rules read it (DB references) "
        "or that its rules read. Uses the extracted metadata graph when the "
        "connection has one, otherwise parses candidate processes live."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {"type": "string", "description": "The cube."},
            "source": {
                "type": "string",
                "enum": ["auto", "graph", "live"],
                "description": "auto (default): the graph if extracted, else live.",
            },
        },
        "required": ["connection_id", "cube_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        cube = required_text(kwargs, "cube_name")
        source = str(kwargs.get("source") or "auto")
        connection_id = connection_id_of(kwargs)

        # Validates the connection belongs to this organization before the
        # graph is consulted, and confirms the cube exists.
        cube_info = await tm1_integration_service.get_cube(
            db, connection_id, organization_id, cube
        )

        if source in ("auto", "graph"):
            graph = await self._from_graph(db, connection_id, organization_id, cube_info.name)

            if graph is not None:
                return json.dumps(graph)

            if source == "graph":
                raise NotFoundException(
                    f"Cube '{cube_info.name}' is not in the metadata graph. Run "
                    "metadata extraction, or use source 'live'."
                )

        return json.dumps(
            await self._live(db, connection_id, organization_id, cube_info.name)
        )

    async def _from_graph(self, db, connection_id, organization_id, cube: str) -> dict | None:
        node = await tm1_object_repository.get_by_name(db, connection_id, "cube", cube)

        if node is None or node.organization_id != organization_id:
            return None

        async def other(rel, attr):
            obj = await tm1_object_repository.get_by_id(db, getattr(rel, attr))
            return obj

        writers, readers, rule_readers, rule_sources = [], [], [], []

        for rel in await tm1_relationship_repository.list_by_to_object(db, node.id):
            obj = await other(rel, "from_object_id")
            if obj is None:
                continue
            if rel.relationship_type == "updates_cube":
                writers.append(obj)
            elif rel.relationship_type == "reads_cube":
                readers.append(obj)
            elif rel.relationship_type == "references_cube":
                rule_readers.append(obj.name)

        for rel in await tm1_relationship_repository.list_by_from_object(
            db, node.id, "references_cube"
        ):
            obj = await other(rel, "to_object_id")
            if obj is not None:
                rule_sources.append(obj.name)

        chores: dict[str, list[str]] = {}

        for writer in writers:
            for rel in await tm1_relationship_repository.list_by_to_object(
                db, writer.id, "runs_process"
            ):
                chore = await other(rel, "from_object_id")
                if chore is not None:
                    chores.setdefault(chore.name, []).append(writer.name)

        return {
            "cube": cube,
            "source": "metadata graph",
            "extracted_at": node.extracted_at.isoformat() if node.extracted_at else None,
            "written_by_processes": sorted(w.name for w in writers),
            "read_by_processes": sorted(r.name for r in readers),
            "chores_running_writers": [
                {"chore": name, "runs": sorted(set(procs))} for name, procs in sorted(chores.items())
            ],
            "read_by_rules_of_cubes": sorted(rule_readers),
            "rules_read_from_cubes": sorted(rule_sources),
            "evidence": evidence(
                verified=["Metadata graph built from TM1 source at the extraction time shown"],
                unknown=[
                    "Changes made on the server since the extraction",
                    "Writes whose cube name is a variable",
                ],
            ),
        }

    async def _live(self, db, connection_id, organization_id, cube: str) -> dict:
        connection, client = await tm1_integration_service.connect(
            db, connection_id, organization_id
        )
        cid = connection.id

        # The server narrows the candidates: only processes whose code
        # mentions the cube's name can reference it by literal.
        candidates = await process_service.search_process_code(client, cid, cube)
        truncated = len(candidates) > MAX_FLOW_PROCESSES
        candidates = candidates[:MAX_FLOW_PROCESSES]
        semaphore = asyncio.Semaphore(CONCURRENCY)
        writers, readers = set(), set()

        async def classify(name: str) -> None:
            async with semaphore:
                try:
                    process = await process_service.get_process(client, cid, name)
                except TM1NotFoundError:
                    return
            record = record_from(process)
            lowered = cube.lower()
            if lowered in {c.lower() for c in record.cubes_written}:
                writers.add(process.name)
            if lowered in {c.lower() for c in record.cubes_read} or (
                record.datasource_name.lower() == lowered
            ):
                readers.add(process.name)

        await asyncio.gather(*(classify(n) for n in candidates))

        rule_readers: list[str] = []

        for other_cube in await cube_service.search_rule_substring(client, cid, cube):
            if other_cube.lower() == cube.lower():
                continue
            rules = await cube_service.get_cube_rules(client, cid, other_cube)
            if cube in extract_rule_cube_references(rules or ""):
                rule_readers.append(other_cube)

        own_rules = await cube_service.get_cube_rules(client, cid, cube)
        rule_sources = sorted(
            c for c in extract_rule_cube_references(own_rules or "") if c != cube
        )

        chores: list[dict] = []
        chore_names = await chore_service.list_chores(client, cid)
        chores_truncated = len(chore_names) > MAX_FLOW_CHORES

        if writers:
            for chore_name in chore_names[:MAX_FLOW_CHORES]:
                chore = await chore_service.get_chore(client, cid, chore_name)
                runs = sorted(p for p in chore.process_names if p in writers)
                if runs:
                    chores.append({"chore": chore.name, "active": chore.active, "runs": runs})

        return {
            "cube": cube,
            "source": "live parse",
            "written_by_processes": sorted(writers),
            "read_by_processes": sorted(readers),
            "chores_running_writers": chores,
            "read_by_rules_of_cubes": sorted(rule_readers),
            "rules_read_from_cubes": rule_sources,
            "truncated": truncated or chores_truncated,
            "evidence": evidence(
                verified=[
                    "Processes whose source mentions the cube found by a server-side search",
                    "Each candidate's source parsed for CellPut/CellIncrement (write) and CellGet (read)",
                    "Rule text of the cube and of cubes whose rules mention it",
                ],
                unknown=[
                    "Processes that write the cube through a variable name "
                    "(sCube = 'X'; CellPutN(v, sCube, …)) are only found when "
                    "the literal also appears in their code",
                    "Processes that read the cube only through a cube-view "
                    "datasource, without naming it in code, are found in graph "
                    "mode (after metadata extraction), not in this live search",
                ]
                + (["Candidate list truncated"] if truncated else []),
            ),
        }
