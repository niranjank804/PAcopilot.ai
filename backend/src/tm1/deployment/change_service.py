import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from TM1py import Process

from src.core.config import settings
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.database.models.tm1_change import TM1Change
from src.repositories.tm1_change_repository import tm1_change_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.deployment import ti_analysis
from src.tm1.exceptions import (
    TM1AuthenticationError,
    TM1NotFoundError,
    TM1OutcomeUnknownError,
)
from src.tm1.impact.analyzer import analyze_impact, needs_acknowledgement
from src.tm1.metadata import dependency_analyzer, extractor
from src.tm1.resilience import call_with_resilience
from src.tm1.service import tm1_integration_service
from src.tm1.services import (
    cell_service,
    cube_service,
    log_service,
    process_service,
    structure_service,
    view_service,
)
from src.tm1.services.mdx_table import execute_mdx_table
from src.tm1.ti.parser import parse_process_code
from src.tm1.ti.review import review

logger = logging.getLogger(__name__)

VALID_CHANGE_TYPES = (
    "update_rules",
    "create_process",
    "update_process",
    "delete_process",
    "run_process",
    "write_cells",
    "create_view",
)

# Cells one write_cells change may set. A change is something a person
# reads before approving; beyond this it is a data load, which is a process.
MAX_CELL_WRITES = 200

# A create_view draft runs its MDX to prove it works. Values are read only
# when the view is this small; a bigger one is proven by TM1 counting it.
VIEW_CHECK_CELLS = 500
# Seconds the check may take: a view that cannot be counted in this long
# is not one anyone will open.
VIEW_CHECK_TIMEOUT = 30
MAX_VIEW_NAME = 100
# TM1 stores a public view as a .vue file named after it, so the
# characters a file name cannot hold are refused, as TM1 itself does.
_VIEW_NAME_FORBIDDEN = set('\\/:*?"<>|')

# Characters of a failed run's error log kept on the change. Enough for
# the lines that matter; the full file stays on the server.
RUN_LOG_EXCERPT_CHARS = 4000


def validate_run_parameters(definitions: list[dict], given: dict) -> list[str]:
    """Problems with the parameters proposed for a run.

    A name the process does not declare, or a non-number for a numeric
    parameter, would otherwise reach TM1 and either be ignored silently
    or fail the run after the approver has already approved it.
    """

    by_name = {(d.get("name") or "").lower(): d for d in definitions}
    problems = []

    for name, value in given.items():
        if str(name).lower() in process_service.RESERVED_RUN_KEYWORDS:
            # TM1py takes these names as its own arguments, so the value
            # could never reach the process: refuse it now, not at run time.
            problems.append(
                f"A parameter named '{name}' cannot be passed to a run by "
                "PA-Copilot. Rename it in the process, or run it from TM1."
            )
            continue

        definition = by_name.get(str(name).lower())

        if definition is None:
            declared = ", ".join(d.get("name") for d in definitions) or "none"
            problems.append(
                f"The process has no parameter '{name}'. Its parameters are: {declared}."
            )
            continue

        if str(definition.get("type") or "").lower() == "numeric":
            try:
                float(value)
            except (TypeError, ValueError):
                problems.append(f"Parameter '{name}' is numeric; '{value}' is not a number.")

    return problems


def run_plan(definitions: list[dict], given: dict, record) -> list[dict]:
    """What the approver needs to see before approving a run: every
    parameter with the value it will actually take, and what the process
    writes and calls according to its source."""

    lowered = {str(k).lower(): v for k, v in given.items()}
    plan: list[dict] = []

    for definition in definitions:
        name = definition.get("name") or ""
        given_value = lowered.get(name.lower())
        plan.append(
            {
                "kind": "parameter",
                "name": name,
                "value": given_value if given_value is not None else definition.get("default"),
                "source": "given" if given_value is not None else "default",
            }
        )

    for cube in sorted(record.cubes_written):
        plan.append({"kind": "writes_cube", "name": cube, "source": "TI parser"})

    for process in sorted(record.processes_called):
        plan.append({"kind": "calls_process", "name": process, "source": "TI parser"})

    unresolved = [o for o in record.objects if not o.literal and o.access in ("write", "calls")]

    if unresolved:
        plan.append(
            {
                "kind": "note",
                "note": (
                    f"{len(unresolved)} write or call target(s) are built from "
                    "variables; what they touch depends on the parameter values."
                ),
            }
        )

    plan.append(
        {
            "kind": "note",
            "note": (
                "A process run cannot be rolled back. Anything it writes stays "
                "written; TM1 does not keep a before-image of a run."
            ),
        }
    )

    return plan

_PROCESS_CODE_FIELDS = {
    "prolog": "prolog_procedure",
    "metadata": "metadata_procedure",
    "data": "data_procedure",
    "epilog": "epilog_procedure",
}


def _apply_datasource(process: Process, content: dict) -> None:
    datasource_type = content.get("datasource_type")
    if not datasource_type:
        return

    process.datasource_type = datasource_type

    if datasource_type == "ASCII":
        name = content.get("datasource_name") or ""
        process.datasource_data_source_name_for_server = name
        process.datasource_data_source_name_for_client = name
        process.datasource_ascii_delimiter_type = "Character"
        process.datasource_ascii_delimiter_char = content.get("ascii_delimiter") or ","
        header = content.get("ascii_header_records")
        process.datasource_ascii_header_records = (
            int(header) if header is not None else 0
        )


def _apply_variables(process: Process, content: dict) -> None:
    if "variables" not in content:
        return

    # Replace rather than append: a re-proposed draft defines the full set.
    # TM1py exposes no clear-all, so the backing lists are reset directly.
    process._variables = []
    process._variables_ui_data = []

    for variable in content["variables"]:
        var_type = "Numeric" if str(variable.get("type")) == "Numeric" else "String"
        process.add_variable(str(variable["name"]), var_type)


def _apply_parameters(process: Process, content: dict) -> None:
    if "parameters" not in content:
        return

    process._parameters = []

    for parameter in content["parameters"]:
        param_type = "Numeric" if str(parameter.get("type")) == "Numeric" else "String"
        raw = parameter.get("value")

        if param_type == "Numeric":
            try:
                value: str | float = float(raw) if raw not in (None, "") else 0
            except (TypeError, ValueError):
                value = 0
        else:
            value = str(raw) if raw is not None else ""

        process.add_parameter(
            str(parameter["name"]),
            str(parameter.get("prompt") or parameter["name"]),
            value,
            parameter_type=param_type,
        )


def _fingerprint(
    change_type: str,
    target_name: str,
    new_content: dict | None,
) -> str:
    """Stable hash of everything that makes a proposal what it is.

    Two proposals with the same fingerprint are the same draft, however
    many times the caller asked for it — a double-clicked button, a
    retried HTTP request, or an agent re-running a tool after a stream
    reconnect.
    """

    payload = json.dumps(
        {
            "change_type": change_type,
            "target_name": target_name,
            "new_content": new_content,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_process(name: str, content: dict, base: dict | None = None) -> Process:
    # A copy starts from the source process exactly as the server returned
    # it. Rebuilding it field by field would drop what the draft format has
    # no slot for — the ASCII quote character, variable positions, UI data —
    # and the copy would quietly differ from the original.
    source_body = content.get("source_body")

    if base:
        process = Process.from_dict(base)
        process.name = name
    elif source_body:
        process = Process.from_dict(source_body)
        process.name = name
    else:
        process = Process(name=name)

    for key, attribute in _PROCESS_CODE_FIELDS.items():
        if key in content:
            setattr(process, attribute, content[key] or "")

    if "has_security_access" in content:
        process.has_security_access = bool(content["has_security_access"])

    if source_body and not base:
        # The simplified datasource, variables and parameters on a copy are
        # there for static analysis only; the body above is already exact.
        return process

    _apply_datasource(process, content)
    _apply_variables(process, content)
    _apply_parameters(process, content)

    return process


def build_candidate(name: str, content: dict, base: dict | None = None) -> Process:
    """A process object as a draft would create it, never saved. Used to
    compile code on the server without persisting it."""

    return _build_process(name, content, base)


_CODE_KEYS = ("PrologProcedure", "MetadataProcedure", "DataProcedure", "EpilogProcedure")


def _code_of(body: dict) -> dict:
    """A process's four code sections as TM1 stores them, for comparing what
    is on the server now with what a change left there."""

    return {key: (body.get(key) or "").replace("\r\n", "\n").strip() for key in _CODE_KEYS}


def _rules_text(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def _changed_since(target: str) -> ConflictException:
    return ConflictException(
        f"'{target}' has been edited since this change was applied. Rolling "
        "back would overwrite those later edits, so nothing was changed. "
        "Review the current version and make a new change instead."
    )


async def _restore_then_raise(restore, original: BaseException):
    """A check after an apply failed outright (not with findings): put the
    previous state back before the error reaches the caller, so a failure
    never leaves an unchecked change on the server."""

    try:
        await restore()
    except Exception:  # noqa: BLE001 - the original error is the one to report
        logger.exception("Restoring the previous state after a failed check also failed")
    raise original


async def _refresh_graph(db: AsyncSession, change: TM1Change, *, deleted: bool) -> None:
    """Keep the dependency map in step with a process change PA-Copilot
    just made, so the next impact question sees it. In a savepoint and
    best-effort: the change on the server has happened either way, and a
    stale map entry is corrected by the next extraction."""

    if not change.change_type.endswith("_process") or change.change_type == "run_process":
        return

    try:
        async with db.begin_nested():
            await extractor.refresh_process(
                db,
                change.connection_id,
                change.organization_id,
                change.target_name,
                deleted=deleted,
            )
    except Exception:  # noqa: BLE001
        logger.warning(f"Dependency map not refreshed for {change.target_name}", exc_info=True)


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def _server_fingerprint(
    client, connection_id, change_type: str, target: str, content: dict | None = None
) -> str | None:
    """The target as the server holds it now, hashed: the rules text, or a
    process's four code sections. None where no later edit could be lost
    (a new process is re-checked for existence instead; a run has no
    content)."""

    if change_type == "update_rules":
        return _hash(_rules_text(await cube_service.get_cube_rules(client, connection_id, target)))
    if change_type in ("update_process", "delete_process"):
        return _hash(_code_of(await process_service.get_process_body(client, connection_id, target)))
    if change_type == "write_cells":
        coordinates = [c for c, _ in _cell_writes(content)]
        return _hash([_normal(v) for v in await _read_values(client, connection_id, target, coordinates)])
    return None


def _normal(value):
    """A value as drift and rollback compare it: empty numeric is 0."""

    if value is None:
        return 0.0
    return round(float(value), 9) if isinstance(value, (int, float)) else value


def _cell_writes(new_content: dict | None) -> list[tuple[list[str], float | str]]:
    """The (coordinates, value) pairs of a write_cells change, checked for
    shape. Raises ValidationException for a request no one could approve."""

    cells = (new_content or {}).get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValidationException("write_cells requires new_content.cells: a list of {coordinates, value}.")
    if len(cells) > MAX_CELL_WRITES:
        raise ValidationException(
            f"A change can write at most {MAX_CELL_WRITES} cells; use a TurboIntegrator "
            "process for a data load."
        )
    writes = []
    for position, cell in enumerate(cells):
        coordinates = cell.get("coordinates") if isinstance(cell, dict) else None
        value = cell.get("value") if isinstance(cell, dict) else None
        if not isinstance(coordinates, list) or not coordinates or not all(
            isinstance(e, str) and e for e in coordinates
        ):
            raise ValidationException(f"Cell {position + 1}: coordinates must be a list of element names.")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValidationException(f"Cell {position + 1}: value must be a number or a string.")
        writes.append((coordinates, value))
    return writes


def _same_value(a, b) -> bool:
    """TM1 reports an empty numeric cell as 0 or None, an empty string cell
    as '' or None; numbers compare with a little float tolerance."""

    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            x, y = float(a or 0), float(b or 0)
        except (TypeError, ValueError):
            return False
        return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))
    return (a or "") == (b or "")


async def _read_values(client, connection_id, cube: str, coordinates: list[list[str]]) -> list:
    result = await cell_service.read_cells(client, connection_id, cube, coordinates)
    if "cells" not in result:
        raise ValidationException(
            result.get("error")
            or "These elements do not exist: "
            + ", ".join(f"{i['dimension']}:{i['element']}" for i in result.get("invalid", []))
        )
    return [cell["value"] for cell in result["cells"]]


def _view_content(new_content: dict | None) -> tuple[str, str]:
    """(view name, MDX) of a create_view change. Raises ValidationException
    for a request with the wrong shape; what is wrong with the values is
    left to the draft's checks."""

    content = new_content if isinstance(new_content, dict) else {}
    view_name, mdx = content.get("view_name"), content.get("mdx")
    if not isinstance(view_name, str) or not isinstance(mdx, str):
        raise ValidationException("create_view requires new_content.view_name and new_content.mdx.")
    return view_name, mdx


def _view_name_problems(view_name: str) -> list[str]:
    if not view_name.strip():
        return ["The view needs a name."]
    problems = []
    if len(view_name) > MAX_VIEW_NAME:
        problems.append(f"A view name can be at most {MAX_VIEW_NAME} characters.")
    forbidden = sorted({c for c in view_name if c in _VIEW_NAME_FORBIDDEN or ord(c) < 32})
    if forbidden:
        shown = " ".join(repr(c) for c in forbidden)
        problems.append(f"TM1 does not allow these characters in a view name: {shown}.")
    if view_name.startswith("}"):
        problems.append("Names starting with '}' are reserved for TM1's control objects.")
    if view_name != view_name.strip():
        problems.append("The view name starts or ends with a space.")
    return problems


# A bracketed name (skipped whole, so a member called [Transfer From X]
# is not read as a FROM clause) or the FROM keyword.
_MDX_TOKEN = re.compile(r"\[(?:[^\]]|\]\])*\]|\bFROM\b", re.IGNORECASE)
# What follows FROM: "[Cube]" (with "]]" for a "]" in the name) or "Cube".
_MDX_FROM_TARGET = re.compile(r"\s*(?:\[((?:[^\]]|\]\])+)\]|([^\s\[\]()]+))")


def _tm1_name(name: str) -> str:
    # TM1 names ignore case and spaces.
    return name.replace(" ", "").lower()


def _mdx_cubes(mdx: str) -> list[str]:
    """Every cube the MDX selects FROM. A sub-select has a FROM per level."""

    cubes = []
    for token in _MDX_TOKEN.finditer(mdx):
        if token.group().startswith("["):
            continue
        target = _MDX_FROM_TARGET.match(mdx, token.end())
        if target:
            bracketed, bare = target.groups()
            cubes.append(bracketed.replace("]]", "]") if bracketed else bare)
    return cubes


def _mdx_cube_problem(mdx: str, cube_name: str) -> str | None:
    cubes = _mdx_cubes(mdx)
    if not cubes:
        return f"The MDX has no FROM [{cube_name}] clause."
    others = sorted({c for c in cubes if _tm1_name(c) != _tm1_name(cube_name)})
    if others:
        return (
            f"The MDX reads from {', '.join(others)}, not from '{cube_name}'. A view "
            "belongs to one cube and must select from it."
        )
    return None


def _mdx_text(mdx: str | None) -> str:
    """MDX as compared after a save: whitespace does not change a query."""

    return " ".join((mdx or "").split())


async def _mdx_run_check(client, connection_id, mdx: str) -> tuple[str | None, str]:
    """(problem, what happened) from running a view's MDX, read-only.

    TM1 counts the cells first, which proves the query parses and runs
    against the cube; a small result is also read. Unreachable server or
    lost credentials are not the MDX's fault, so those still raise."""

    try:
        total = int(await call_with_resilience(
            connection_id,
            client.cubes.cells.execute_mdx_cellcount,
            mdx,
            timeout=VIEW_CHECK_TIMEOUT,
            max_retries=0,
        ))
        if total > VIEW_CHECK_CELLS:
            return None, f"TM1 ran it: {total:,} cells (too many to read in a check)"
        table = await execute_mdx_table(
            client, connection_id, mdx, timeout=VIEW_CHECK_TIMEOUT, max_retries=0
        )
    except (TM1OutcomeUnknownError, TM1AuthenticationError):
        raise
    except Exception as exc:  # noqa: BLE001 - recorded on the draft
        return f"TM1 could not run the MDX: {getattr(exc, 'message', None) or exc}", "failed"
    return None, f"TM1 ran it: {total:,} cells, {len(table['rows'])} with a value"


def _check(name: str, status: str, detail: str, items: list | None = None) -> dict:
    entry = {"name": name, "status": status, "detail": detail}
    if items:
        entry["items"] = items[:10]
    return entry


def _impact_check(impact: list) -> dict:
    counts = {s: 0 for s in ("critical", "high", "medium", "low")}
    for entry in impact or []:
        if isinstance(entry, dict) and entry.get("severity") in counts:
            counts[entry["severity"]] += 1
    serious = counts["critical"] + counts["high"]
    detail = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "nothing in the dependency map depends on it"
    return _check(
        "Impact",
        "warn" if serious else "pass",
        detail + (" — the approver must confirm reading it" if serious else ""),
    )


class ChangeService:

    async def _client(self, db, connection):
        return await tm1_connection_manager.get_client(connection)

    async def _impact(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        object_type: str,
        name: str,
        change_type: str,
    ) -> list:
        """What this change affects, ranked (src/tm1/impact/analyzer.py),
        stored on the draft so the approver sees it and approval can
        require it was read."""

        result = await analyze_impact(
            db,
            connection_id,
            organization_id,
            object_type,
            name,
            change_kind="delete" if change_type == "delete_process" else "modify",
            rules_change=change_type == "update_rules",
        )

        if not result["in_graph"]:
            return [{"note": result["not_covered"][0]}]

        entries: list = list(result["items"])
        if result["graph"].get("note"):
            entries.append({"note": result["graph"]["note"]})
        return entries

    async def create_change(
        self,
        db: AsyncSession,
        *,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        created_by: uuid.UUID,
        change_type: str,
        target_name: str,
        new_content: dict | None,
    ) -> TM1Change:

        checks: list[dict] = []

        if change_type not in VALID_CHANGE_TYPES:
            raise ValidationException(f"Unknown change_type '{change_type}'.")

        # Resolved before any TM1 round trip so a repeated proposal costs
        # nothing. Scoped to this author: superseding a colleague's open
        # draft out from under them would be a surprise, so a second
        # person proposing against the same target gets their own draft.
        fingerprint = _fingerprint(change_type, target_name, new_content)

        open_drafts = await tm1_change_repository.list_open_drafts(
            db,
            connection_id=connection_id,
            organization_id=organization_id,
            created_by=created_by,
            change_type=change_type,
            target_name=target_name,
        )

        if change_type == "create_view":
            # The target is the cube; the view name is part of the open-draft
            # key (uq_tm1_changes_open_draft). A draft of the same view is
            # replaced as usual; drafts of other views on this cube are
            # their own pending work and are left alone.
            view_name = str((new_content or {}).get("view_name") or "")
            open_drafts = [
                draft for draft in open_drafts
                if str((draft.new_content or {}).get("view_name") or "") == view_name
            ]

        for draft in open_drafts:
            if (
                _fingerprint(
                    draft.change_type, draft.target_name, draft.new_content
                )
                == fingerprint
            ):
                return draft

        connection = await tm1_integration_service.get_connection(
            db, connection_id, organization_id
        )
        client = await self._client(db, connection)

        validation_errors: list = []

        if change_type == "update_rules":
            if not new_content or "rules" not in new_content:
                raise ValidationException(
                    "update_rules requires new_content.rules."
                )
            # Target must exist (raises TM1NotFoundError otherwise). No rule
            # dry-run exists in TM1 — real validation happens at execute.
            await cube_service.get_cube(client, connection.id, target_name)
            object_type = "cube"
            checks = [
                _check(
                    "Rule syntax",
                    "info",
                    "TM1 has no dry run for rules: they are checked right after "
                    "they are applied, and the previous rules are restored "
                    "automatically if the check fails",
                ),
            ]

        elif change_type in ("create_process", "update_process"):
            if new_content is None:
                raise ValidationException(
                    f"{change_type} requires new_content."
                )

            exists = await process_service.process_exists(
                client, connection.id, target_name
            )

            if change_type == "create_process" and exists:
                raise ConflictException(
                    f"Process '{target_name}' already exists — use update_process."
                )

            if change_type == "update_process" and not exists:
                raise TM1NotFoundError(f"Process '{target_name}' not found.")

            base = None
            if change_type == "update_process":
                base = await process_service.get_process_body(
                    client, connection.id, target_name
                )

            candidate = _build_process(target_name, new_content, base)

            # Static analysis first: it catches defects the compiler
            # tolerates (inconsistent variable casing) or reports at the
            # use site rather than the missing declaration. The server's
            # own datasource is passed through so an update that doesn't
            # touch the datasource is still analysed against the right one
            # — a cube-view process has generated source variables that no
            # draft can declare.
            errors = await process_service.compile_process_dryrun(
                client, connection.id, candidate
            )
            static_errors = ti_analysis.analyze(
                new_content,
                datasource_type=(base or {}).get("DataSourceType"),
            )
            validation_errors = static_errors + (errors or [])
            object_type = "process"

            findings, _ = review(parse_process_code(
                target_name,
                prolog=candidate.prolog_procedure or "",
                metadata=candidate.metadata_procedure or "",
                data=candidate.data_procedure or "",
                epilog=candidate.epilog_procedure or "",
                datasource_type=(base or {}).get("DataSourceType") or "None",
                datasource_name="",
            ))
            concerns = [f for f in findings if f.severity in ("error", "warning")]
            checks = [
                _check(
                    "Static analysis",
                    "fail" if static_errors else "pass",
                    f"{len(static_errors)} problem(s) found" if static_errors else "no undeclared or misspelled names",
                    [e.get("Message", str(e)) if isinstance(e, dict) else str(e) for e in static_errors],
                ),
                _check(
                    "Compiled on the server (not saved)",
                    "fail" if errors else "pass",
                    f"{len(errors)} compile error(s)" if errors else "TM1 compiled it without errors",
                    [f"{e.get('Procedure', '')} line {e.get('LineNumber', '?')}: {e.get('Message', '')}" for e in errors or []],
                ),
                _check(
                    "Code review",
                    "warn" if concerns else "pass",
                    (
                        f"{len(concerns)} finding(s) to look at before approving"
                        if concerns
                        else "no dangerous operations or errors found"
                    ),
                    [f"{f.category}: {f.evidence}" for f in concerns],
                ),
            ]

        elif change_type == "run_process":
            # Raises TM1NotFoundError for a process that does not exist.
            process = await process_service.get_process(
                client, connection.id, target_name
            )
            given = (new_content or {}).get("parameters") or {}

            if not isinstance(given, dict):
                raise ValidationException("run_process parameters must be an object.")

            validation_errors = validate_run_parameters(process.parameters, given)
            checks = [
                _check(
                    "Parameters",
                    "fail" if validation_errors else "pass",
                    f"{len(validation_errors)} problem(s)" if validation_errors
                    else "every value matches a parameter the process declares",
                    validation_errors,
                ),
                _check(
                    "No rollback",
                    "warn",
                    "A run writes data directly; it cannot be rolled back. Check "
                    "the values and the cubes it writes before approving",
                ),
            ]
            record = parse_process_code(
                process.name,
                prolog=process.prolog,
                metadata=process.metadata,
                data=process.data,
                epilog=process.epilog,
                datasource_type=process.datasource_type,
                datasource_name=process.datasource_name,
                parameters=process.parameters,
                variables=process.variables,
            )
            object_type = None
            run_impact = run_plan(process.parameters, given, record)

        elif change_type == "write_cells":
            writes = _cell_writes(new_content)
            coordinates = [c for c, _ in writes]
            result = await cell_service.read_cells(client, connection.id, target_name, coordinates)
            if "cells" not in result:
                validation_errors.append(
                    result.get("error")
                    or "These elements do not exist: "
                    + ", ".join(f"{i['dimension']}:{i['element']}" for i in result.get("invalid", []))
                )
                cells = []
            else:
                cells = result["cells"]

            seen = set()
            changing = 0
            for (coords, value), cell in zip(writes, cells):
                where = ", ".join(coords)
                if tuple(coords) in seen:
                    validation_errors.append(f"{where}: listed more than once.")
                seen.add(tuple(coords))
                if cell.get("consolidated"):
                    validation_errors.append(
                        f"{where}: a consolidated cell. Writing it would spread the value "
                        "over its children; write the leaf cells instead."
                    )
                elif cell.get("rule_derived"):
                    validation_errors.append(f"{where}: calculated by a rule, so it cannot be written.")
                current = cell.get("value")
                if isinstance(current, str) != isinstance(value, str) and current is not None:
                    validation_errors.append(
                        f"{where}: a {'string' if isinstance(current, str) else 'numeric'} cell; "
                        f"the value {value!r} does not fit."
                    )
                if not _same_value(current, value):
                    changing += 1

            checks += [
                _check(
                    "Cells",
                    "fail" if validation_errors else "pass",
                    f"{len(validation_errors)} problem(s)" if validation_errors
                    else f"{len(writes)} leaf cell(s), {changing} with a new value; none consolidated or rule-calculated",
                    validation_errors,
                ),
                _check(
                    "Current values",
                    "info",
                    "Read from the server now; they are saved again when the change is "
                    "applied, and if they have changed by then nothing is written",
                ),
            ]
            object_type = "cube"

        elif change_type == "create_view":
            view_name, mdx = _view_content(new_content)
            # The cube must exist (raises TM1NotFoundError otherwise).
            await cube_service.get_cube(client, connection.id, target_name)

            view_problems = _view_name_problems(view_name)
            if not view_problems and await view_service.view_exists(
                client, connection.id, target_name, view_name
            ):
                # Never overwrite or modify a view someone already has.
                view_problems.append(
                    f"A public view named '{view_name}' already exists on '{target_name}'. "
                    "Choose another name; an existing view is never replaced."
                )

            if not mdx.strip():
                mdx_problem, mdx_detail = "The view needs MDX.", "no MDX given"
            else:
                mdx_problem = _mdx_cube_problem(mdx, target_name)
                mdx_detail = "not run: it must select from this cube"
                if mdx_problem is None:
                    mdx_problem, mdx_detail = await _mdx_run_check(client, connection.id, mdx)

            validation_errors = view_problems + ([mdx_problem] if mdx_problem else [])
            checks = [
                _check(
                    "View",
                    "fail" if view_problems else "pass",
                    f"{len(view_problems)} problem(s)" if view_problems
                    else f"a new public view '{view_name}' on '{target_name}'; no view of that name exists",
                    view_problems,
                ),
                _check(
                    "MDX runs",
                    "fail" if mdx_problem else "pass",
                    mdx_detail,
                    [mdx_problem] if mdx_problem else None,
                ),
            ]
            object_type = None

        else:  # delete_process
            exists = await process_service.process_exists(
                client, connection.id, target_name
            )
            if not exists:
                raise TM1NotFoundError(f"Process '{target_name}' not found.")
            object_type = "process"

        # A run's impact is its plan: parameter values and what it writes.
        # A new view has no dependents. Everything else uses the dependency
        # graph.
        if change_type == "run_process":
            impact = run_impact
        elif change_type == "create_view":
            impact = []
        else:
            impact = await self._impact(
                db, connection.id, organization_id, object_type, target_name, change_type
            )

        if change_type == "create_view":
            checks.append(_check("Impact", "info", "A new public view; nothing depends on it yet"))
            checks.append(_check(
                "Snapshot and rollback",
                "info",
                "Nothing existing is changed. Roll back deletes the view, and only "
                "if it is unchanged since it was created",
            ))
        elif change_type != "run_process":
            checks.append(_impact_check(impact))
            checks.append(_check(
                "Snapshot and rollback",
                "info",
                "The current version is saved when the change is applied, and "
                "can be restored with Roll back",
            ))
        # A draft that can never be applied has nothing to protect from drift.
        base_fingerprint = None if validation_errors else await _server_fingerprint(
            client, connection.id, change_type, target_name, new_content
        )

        # An agent that calls propose_process_update several times in one
        # turn produces several proposals against the same target. Each one
        # replaces the last, so the turn ends with exactly one executable
        # draft rather than N competing ones.
        #
        # Split in two because the constraints pull opposite ways:
        # uq_tm1_changes_open_draft needs the old row out of 'draft' before
        # the insert, while superseded_by's foreign key needs the new row to
        # exist before it can be pointed at. Status first, pointer after.
        for draft in open_drafts:
            draft.status = "superseded"
            await tm1_change_repository.update(db, draft)

        change = TM1Change(
            connection_id=connection.id,
            organization_id=organization_id,
            created_by=created_by,
            change_type=change_type,
            target_name=target_name,
            new_content=new_content,
            validation_errors=validation_errors or None,
            impact=impact,
            status="draft",
            base_fingerprint=base_fingerprint,
            checks=checks or None,
            environment=getattr(connection, "environment", None) or "dev",
        )

        created = await tm1_change_repository.create(db, change)

        for draft in open_drafts:
            draft.superseded_by = created.id
            await tm1_change_repository.update(db, draft)

        return created

    async def get_change_preview(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> dict:

        connection = await tm1_integration_service.get_connection(
            db, change.connection_id, change.organization_id
        )
        client = await self._client(db, connection)

        current: dict | None
        try:
            if change.change_type == "update_rules":
                current = {
                    "rules": await cube_service.get_cube_rules(
                        client, connection.id, change.target_name
                    )
                }
            elif change.change_type == "write_cells":
                coordinates = [c for c, _ in _cell_writes(change.new_content)]
                values = await _read_values(client, connection.id, change.target_name, coordinates)
                current = {
                    "cells": [
                        {"coordinates": c, "value": v} for c, v in zip(coordinates, values)
                    ]
                }
            elif change.change_type == "create_view":
                view_name, _ = _view_content(change.new_content)
                # None until it is created: the view is new.
                current = (
                    {"view": await structure_service.get_view(
                        client, connection.id, change.target_name, view_name
                    )}
                    if await view_service.view_exists(
                        client, connection.id, change.target_name, view_name
                    )
                    else None
                )
            else:
                current = {
                    "process": await process_service.get_process_body(
                        client, connection.id, change.target_name
                    )
                }
        except TM1NotFoundError:
            current = None

        return {
            "current": current,
            "proposed": change.new_content,
            "impact": change.impact,
            "validation_errors": change.validation_errors,
        }

    @staticmethod
    def lifecycle(change: TM1Change) -> list[dict]:
        """Where the change is in its life, step by step, from the record.

        Each step is done, current, failed, skipped or pending. Nothing is
        inferred: a step is done only when the record shows it happened.
        """

        is_run = change.change_type == "run_process"
        status = change.status
        drafted = {"at": change.created_at}
        valid = not change.validation_errors
        decided = change.executed_at is not None
        outcome_failed = status == "failed"

        def step(key, label, state, at=None, detail=None):
            return {"key": key, "label": label, "state": state, "at": at, "detail": detail}

        steps = [
            step("requested", "Requested", "done", **drafted,
                 detail="drafted by the AI assistant" if (change.new_content or {}).get("ai_generated") else None),
            step("analyzed", "Impact analysed" if not is_run else "Run plan prepared", "done", **drafted),
            step("validated", "Validated", "done" if valid else "failed", **drafted,
                 detail=None if valid else f"{len(change.validation_errors)} problem(s): cannot be approved"),
            step("diff", "Diff ready" if not is_run else "Values shown", "done", **drafted),
        ]

        if status in ("rejected", "superseded"):
            steps.append(step("approval", "Approval", "skipped",
                              detail="rejected" if status == "rejected" else "replaced by a newer draft"))
            return steps

        if not decided:
            steps.append(step("approval", "Approval", "current" if valid else "pending",
                              detail="waiting for someone with deploy rights" if valid else None))
            for key, label in (("snapshot", "Snapshot"), ("deployed", "Applied" if not is_run else "Run"),
                               ("verified", "Verified")):
                steps.append(step(key, label, "pending"))
            return steps

        steps.append(step("approval", "Approved", "done", at=change.executed_at))
        if status == "unknown":
            # Sent, never confirmed: neither done nor failed.
            steps.append(step("deployed", "Applied" if not is_run else "Run", "unknown",
                              at=change.executed_at, detail=change.error_message))
            steps.append(step("verified", "Verified", "pending",
                              detail="check the object on the server"))
            return steps
        if not is_run:
            steps.append(step("snapshot", "Snapshot", "done" if change.previous_content else "skipped",
                              at=change.executed_at))
        steps.append(step("deployed", "Applied" if not is_run else "Run",
                          "failed" if outcome_failed else "done", at=change.executed_at,
                          detail=change.error_message if outcome_failed else None))
        steps.append(step("verified", "Verified",
                          "failed" if outcome_failed else "done", at=change.executed_at,
                          detail=(
                              "TM1 reported the outcome" if is_run
                              else "checked by TM1 after applying; restored automatically on failure"
                          )))
        if change.rolled_back_at:
            steps.append(step("rolled_back", "Rolled back", "done", at=change.rolled_back_at))

        return steps

    @staticmethod
    async def _lock(db: AsyncSession, change: TM1Change) -> TM1Change:
        """Serialise the status transitions on one draft.

        Without this, two executors that both read "draft" — a double
        click, or two admins — both wrote to TM1, and the second write
        raced the first's snapshot. Held until the request's transaction
        commits, which is after the TM1 write, so the second caller then
        reads "executed" and gets the 409 it should.
        """

        locked = await tm1_change_repository.lock_for_update(db, change.id)

        return locked if locked is not None else change

    async def execute_change(
        self,
        db: AsyncSession,
        change: TM1Change,
        executed_by: uuid.UUID,
        acknowledge_impact: bool = False,
    ) -> TM1Change:

        change = await self._lock(db, change)

        if change.status != "draft":
            raise ConflictException(
                f"Only draft changes can be executed (status: {change.status})."
            )

        if change.validation_errors:
            raise ValidationException(
                "This draft has validation errors and cannot be executed."
            )

        # A change that reaches critical or high-severity objects is applied
        # only once the approver has confirmed reading what it affects.
        if needs_acknowledgement(change.impact) and not acknowledge_impact:
            serious = sum(
                1 for e in change.impact
                if isinstance(e, dict) and e.get("severity") in ("critical", "high")
            )
            raise ValidationException(
                f"This change affects {serious} critical or high-severity "
                "object(s). Review its impact and confirm before applying it."
            )

        connection = await tm1_integration_service.get_connection(
            db, change.connection_id, change.organization_id
        )
        client = await self._client(db, connection)

        # Drift: the draft was made against the server as it was then. If the
        # target was edited in TM1 since, applying would overwrite that
        # edit — refuse, and say so, rather than lose someone's work.
        if change.base_fingerprint:
            current = await _server_fingerprint(
                client, connection.id, change.change_type, change.target_name, change.new_content
            )
            if current != change.base_fingerprint:
                raise ConflictException(
                    f"'{change.target_name}' was changed on the TM1 server after "
                    "this draft was made. Applying it would overwrite that "
                    "change, so nothing was applied. Make a new draft from the "
                    "current version."
                )

        change.executed_by = executed_by
        change.executed_at = datetime.now(timezone.utc)

        try:
            return await self._apply(db, change, client, connection)
        except TM1OutcomeUnknownError as exc:
            if change.previous_content is None:
                # The snapshot read failed: nothing was sent to TM1 yet.
                raise
            # The write was sent and TM1 did not confirm it. It may have
            # been applied, partly or fully. Saying 'failed' could invite a
            # second apply; saying nothing left a draft that looked unrun.
            change.status = "unknown"
            change.error_message = (
                f"{exc.message} TM1 did not confirm the change, so it may or may "
                "not have been applied. Check the object on the server; then make "
                "a new draft from what is there now."
            )
            return await tm1_change_repository.update(db, change)

    async def _apply(self, db, change: TM1Change, client, connection) -> TM1Change:
        """Snapshot, write, verify — per change type. Every write is single-
        attempt; previous_content is set before the first write is sent."""

        if change.change_type == "update_rules":
            previous = await cube_service.get_cube_rules(
                client, connection.id, change.target_name
            )
            change.previous_content = {"rules": previous}

            await cube_service.update_cube_rules(
                client, connection.id, change.target_name,
                change.new_content["rules"],
            )

            async def restore_rules():
                await cube_service.update_cube_rules(
                    client, connection.id, change.target_name, previous or ""
                )

            try:
                errors = await cube_service.check_cube_rules(
                    client, connection.id, change.target_name
                )
            except Exception as exc:  # noqa: BLE001
                await _restore_then_raise(restore_rules, exc)

            if errors is None:
                # TM1 11.0: no rule check exists; the server validated the
                # syntax when it accepted the save. Say which check ran.
                change.checks = [*(change.checks or []), _check(
                    "Server rule check", "info",
                    "This TM1 version has no separate rule check; it validated the rule "
                    "syntax when it accepted the save",
                )]
                errors = []

            if errors:
                # No rule dry-run exists: restore the snapshot immediately.
                await cube_service.update_cube_rules(
                    client, connection.id, change.target_name, previous or ""
                )
                change.status = "failed"
                change.validation_errors = errors
                change.error_message = (
                    "Rule check failed after apply; previous rules restored."
                )
                return await tm1_change_repository.update(db, change)

            change.previous_content = {
                "rules": previous,
                # What this change left on the server, so a rollback can
                # tell whether anyone has edited the rules since.
                "applied": _rules_text(
                    await cube_service.get_cube_rules(
                        client, connection.id, change.target_name
                    )
                ),
            }

        elif change.change_type == "create_process":
            # Checked when drafted, and again now: a process of this name
            # created in between would be overwritten, and its rollback would
            # then delete it with no snapshot to restore.
            if await process_service.process_exists(
                client, connection.id, change.target_name
            ):
                raise ConflictException(
                    f"A process named '{change.target_name}' was created after "
                    "this draft was made. Nothing was changed; draft an update "
                    "to it instead."
                )

            change.previous_content = {"existed": False}

            candidate = _build_process(change.target_name, change.new_content)
            await process_service.update_or_create_process(
                client, connection.id, candidate
            )

            async def remove_created():
                await process_service.delete_process(
                    client, connection.id, change.target_name
                )

            try:
                errors = await process_service.compile_process_on_server(
                    client, connection.id, change.target_name
                )
            except Exception as exc:  # noqa: BLE001
                await _restore_then_raise(remove_created, exc)

            if errors:
                await process_service.delete_process(
                    client, connection.id, change.target_name
                )
                change.status = "failed"
                change.validation_errors = errors
                change.error_message = (
                    "Compile failed after create; process removed."
                )
                return await tm1_change_repository.update(db, change)

            change.previous_content = {
                "existed": False,
                "applied": _code_of(
                    await process_service.get_process_body(
                        client, connection.id, change.target_name
                    )
                ),
            }

        elif change.change_type == "update_process":
            base = await process_service.get_process_body(
                client, connection.id, change.target_name
            )
            change.previous_content = {"process": base}

            candidate = _build_process(change.target_name, change.new_content, base)
            await process_service.update_or_create_process(
                client, connection.id, candidate
            )

            async def restore_base():
                await process_service.update_or_create_process(
                    client, connection.id, Process.from_dict(base)
                )

            try:
                errors = await process_service.compile_process_on_server(
                    client, connection.id, change.target_name
                )
            except Exception as exc:  # noqa: BLE001
                await _restore_then_raise(restore_base, exc)

            if errors:
                await process_service.update_or_create_process(
                    client, connection.id, Process.from_dict(base)
                )
                change.status = "failed"
                change.validation_errors = errors
                change.error_message = (
                    "Compile failed after update; previous version restored."
                )
                return await tm1_change_repository.update(db, change)

            change.previous_content = {
                "process": base,
                "applied": _code_of(
                    await process_service.get_process_body(
                        client, connection.id, change.target_name
                    )
                ),
            }

        elif change.change_type == "run_process":
            return await self._run(db, change, client, connection)

        elif change.change_type == "write_cells":
            writes = _cell_writes(change.new_content)
            coordinates = [c for c, _ in writes]
            dimensions = (await cube_service.get_cube(client, connection.id, change.target_name)).dimensions
            before = await _read_values(client, connection.id, change.target_name, coordinates)
            change.previous_content = {
                "cells": [{"coordinates": c, "value": v} for c, v in zip(coordinates, before)],
            }

            async def restore_cells():
                await cell_service.write_cells(
                    client, connection.id, change.target_name, dimensions,
                    [(c, v if v is not None else 0) for c, v in zip(coordinates, before)],
                )

            await cell_service.write_cells(client, connection.id, change.target_name, dimensions, writes)

            try:
                after = await _read_values(client, connection.id, change.target_name, coordinates)
            except Exception as exc:  # noqa: BLE001
                await _restore_then_raise(restore_cells, exc)

            wrong = [
                f"{', '.join(c)}: wrote {v!r}, the server holds {a!r}"
                for (c, v), a in zip(writes, after)
                if not _same_value(a, v)
            ]
            if wrong:
                await restore_cells()
                change.status = "failed"
                change.validation_errors = wrong
                change.error_message = (
                    "The server did not hold the written values; the previous values were "
                    "written back."
                )
                return await tm1_change_repository.update(db, change)

            change.previous_content = {
                **change.previous_content,
                # What this change left there, so a rollback can tell whether
                # anyone has written these cells since.
                "applied": [_normal(v) for v in after],
            }

        elif change.change_type == "create_view":
            view_name, mdx = _view_content(change.new_content)
            cube = change.target_name
            # Checked when drafted, and again now: a view of this name made
            # in between would be overwritten, and its rollback would then
            # delete someone else's view.
            if await view_service.view_exists(client, connection.id, cube, view_name):
                raise ConflictException(
                    f"A public view named '{view_name}' was created on '{cube}' after "
                    "this draft was made. Nothing was changed; draft the view under "
                    "another name."
                )

            change.previous_content = {"existed": False}
            change.execution_result = {"view": view_name, "cube": cube, "private": False}

            await view_service.create_mdx_view(client, connection.id, cube, view_name, mdx)

            async def remove_view():
                await view_service.delete_view(client, connection.id, cube, view_name)

            try:
                saved = await structure_service.get_view(client, connection.id, cube, view_name)
            except Exception as exc:  # noqa: BLE001
                await _restore_then_raise(remove_view, exc)

            if saved.get("type") != "mdx" or _mdx_text(saved.get("mdx")) != _mdx_text(mdx):
                await remove_view()
                change.status = "failed"
                change.validation_errors = [
                    "The view TM1 saved does not hold the MDX that was approved."
                ]
                change.error_message = (
                    "The view read back did not match the approved MDX; the view was deleted."
                )
                return await tm1_change_repository.update(db, change)

            change.previous_content = {
                "existed": False,
                # What this change left there, so a rollback deletes the
                # view only while it is still exactly this.
                "applied": _mdx_text(saved.get("mdx")),
            }

        else:  # delete_process
            base = await process_service.get_process_body(
                client, connection.id, change.target_name
            )
            change.previous_content = {"process": base}

            await process_service.delete_process(
                client, connection.id, change.target_name
            )

        change.status = "executed"
        await _refresh_graph(db, change, deleted=change.change_type == "delete_process")

        return await tm1_change_repository.update(db, change)

    async def _run(self, db, change: TM1Change, client, connection) -> TM1Change:
        """Perform an approved run and record exactly what TM1 said.

        Never retried. On a timeout TM1 has been asked to cancel, but the
        run may have written some data first, so the change is marked
        failed with that said plainly rather than left as a draft someone
        might approve again.
        """

        parameters = (change.new_content or {}).get("parameters") or {}

        try:
            result = await process_service.execute_process(
                client,
                connection.id,
                change.target_name,
                parameters,
                timeout=settings.TM1_PROCESS_RUN_TIMEOUT_SECONDS,
            )
        except TM1OutcomeUnknownError as exc:
            # No answer: TM1 may have run it, partly or fully.
            change.status = "unknown"
            change.execution_result = {"success": None, "status": "NoResponse"}
            change.error_message = (
                f"{exc.message} TM1 was asked to cancel the run. It may have "
                "written some data before stopping: check the message log "
                "before running it again."
            )
            return await tm1_change_repository.update(db, change)
        except Exception as exc:  # noqa: BLE001 - recorded on the change, not a 500
            # The process deleted since approval, a value TM1 refused, an
            # unexpected TM1py error: the run did not start, and the change
            # says so rather than staying approved-but-unrun.
            logger.warning(f"Approved run of {change.target_name} did not start: {exc!r}")
            change.status = "failed"
            change.execution_result = {"success": False, "status": "NotStarted"}
            change.error_message = (
                "The run could not be started: "
                f"{getattr(exc, 'message', None) or type(exc).__name__}."
            )
            return await tm1_change_repository.update(db, change)

        if not result["success"] and result.get("error_log_file"):
            try:
                content = await log_service.get_process_error_log(
                    client, connection.id, result["error_log_file"]
                )
                result["error_log_excerpt"] = content[:RUN_LOG_EXCERPT_CHARS]
                result["error_locations"] = log_service.parse_error_locations(content)
            except Exception:  # noqa: BLE001 - the run result matters more
                result["error_log_excerpt"] = None

        change.execution_result = result

        if result["success"]:
            change.status = "executed"
        else:
            change.status = "failed"
            change.error_message = (
                f"TM1 reported {result['status']}."
                + (f" {result['error_detail']}" if result.get("error_detail") else "")
                + (
                    f" Error log: {result['error_log_file']}."
                    if result.get("error_log_file")
                    else ""
                )
            )

        return await tm1_change_repository.update(db, change)

    async def reject_change(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> TM1Change:

        change = await self._lock(db, change)

        if change.status != "draft":
            raise ConflictException(
                f"Only draft changes can be rejected (status: {change.status})."
            )

        change.status = "rejected"

        return await tm1_change_repository.update(db, change)

    async def rollback_change(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> TM1Change:

        change = await self._lock(db, change)

        if change.change_type == "run_process":
            raise ConflictException(
                "A process run cannot be rolled back: TM1 keeps no "
                "before-image of what a run writes. Reverse its effect with "
                "another process, or restore from a backup."
            )

        if change.status != "executed":
            raise ConflictException(
                f"Only executed changes can be rolled back (status: {change.status})."
            )

        connection = await tm1_integration_service.get_connection(
            db, change.connection_id, change.organization_id
        )
        client = await self._client(db, connection)
        previous = change.previous_content or {}

        # Restore only over what this change left there; never over later
        # edits. Changes applied before "applied" was recorded restore as
        # they always did.
        if change.change_type == "update_rules":
            if "applied" in previous and _rules_text(
                await cube_service.get_cube_rules(client, connection.id, change.target_name)
            ) != previous["applied"]:
                raise _changed_since(change.target_name)

        elif change.change_type == "write_cells":
            saved = previous.get("cells") or []
            now = await _read_values(
                client, connection.id, change.target_name, [c["coordinates"] for c in saved]
            )
            if [_normal(v) for v in now] != previous.get("applied"):
                raise ConflictException(
                    f"Cells in '{change.target_name}' have been written since this change "
                    "was applied. Rolling back would overwrite those values, so nothing "
                    "was changed."
                )

        elif change.change_type == "create_view":
            # Delete only the view this change created, exactly as it left
            # it: a view edited or recreated since is someone else's work.
            view_name, _ = _view_content(change.new_content)
            label = f"{change.target_name}: {view_name}"
            if not await view_service.view_exists(
                client, connection.id, change.target_name, view_name
            ):
                raise ConflictException(
                    f"The view '{label}' has been deleted since this change was "
                    "applied; nothing was changed."
                )
            saved = await structure_service.get_view(
                client, connection.id, change.target_name, view_name
            )
            if (
                "applied" not in previous
                or saved.get("type") != "mdx"
                or _mdx_text(saved.get("mdx")) != previous["applied"]
            ):
                raise _changed_since(label)

        elif change.change_type == "delete_process":
            if await process_service.process_exists(client, connection.id, change.target_name):
                raise ConflictException(
                    f"A process named '{change.target_name}' exists again since "
                    "it was deleted. Restoring the old one would overwrite it, "
                    "so nothing was changed."
                )

        elif "applied" in previous:  # create_process / update_process
            if not await process_service.process_exists(
                client, connection.id, change.target_name
            ):
                if change.change_type == "update_process":
                    raise ConflictException(
                        f"'{change.target_name}' has been deleted since this "
                        "change was applied; nothing was restored."
                    )
            elif _code_of(
                await process_service.get_process_body(client, connection.id, change.target_name)
            ) != previous["applied"]:
                raise _changed_since(change.target_name)

        if change.change_type == "update_rules":
            await cube_service.update_cube_rules(
                client, connection.id, change.target_name,
                change.previous_content.get("rules") or "",
            )

        elif change.change_type == "write_cells":
            saved = change.previous_content.get("cells") or []
            dimensions = (await cube_service.get_cube(client, connection.id, change.target_name)).dimensions
            await cell_service.write_cells(
                client, connection.id, change.target_name, dimensions,
                [(c["coordinates"], c["value"] if c["value"] is not None else 0) for c in saved],
            )

        elif change.change_type == "create_view":
            await view_service.delete_view(
                client, connection.id, change.target_name,
                _view_content(change.new_content)[0],
            )

        elif change.change_type == "create_process":
            # Already gone: nothing left to remove.
            if await process_service.process_exists(
                client, connection.id, change.target_name
            ):
                await process_service.delete_process(
                    client, connection.id, change.target_name
                )

        else:  # update_process / delete_process — restore the snapshot
            await process_service.update_or_create_process(
                client, connection.id,
                Process.from_dict(change.previous_content["process"]),
            )

        change.status = "rolled_back"
        change.rolled_back_at = datetime.now(timezone.utc)
        await _refresh_graph(db, change, deleted=change.change_type == "create_process")

        return await tm1_change_repository.update(db, change)


change_service = ChangeService()
