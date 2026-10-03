import hashlib
import json
import logging
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
from src.tm1.exceptions import TM1ConnectionError, TM1NotFoundError
from src.tm1.metadata import dependency_analyzer
from src.tm1.service import tm1_integration_service
from src.tm1.services import cube_service, log_service, process_service
from src.tm1.ti.parser import parse_process_code

logger = logging.getLogger(__name__)

VALID_CHANGE_TYPES = (
    "update_rules",
    "create_process",
    "update_process",
    "delete_process",
    "run_process",
)

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
    ) -> list:
        try:
            return await dependency_analyzer.find_dependents(
                db, connection_id, organization_id, object_type, name
            )
        except NotFoundException:
            return [
                {
                    "note": (
                        f"{object_type} '{name}' is not in the metadata graph — "
                        "run metadata extraction for impact analysis."
                    )
                }
            ]

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
            validation_errors = ti_analysis.analyze(
                new_content,
                datasource_type=(base or {}).get("DataSourceType"),
            ) + (errors or [])
            object_type = "process"

        elif change_type == "run_process":
            # Raises TM1NotFoundError for a process that does not exist.
            process = await process_service.get_process(
                client, connection.id, target_name
            )
            given = (new_content or {}).get("parameters") or {}

            if not isinstance(given, dict):
                raise ValidationException("run_process parameters must be an object.")

            validation_errors = validate_run_parameters(process.parameters, given)
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

        else:  # delete_process
            exists = await process_service.process_exists(
                client, connection.id, target_name
            )
            if not exists:
                raise TM1NotFoundError(f"Process '{target_name}' not found.")
            object_type = "process"

        # A run's impact is its plan: parameter values and what it writes.
        # Everything else uses the dependency graph.
        impact = (
            run_impact
            if change_type == "run_process"
            else await self._impact(
                db, connection.id, organization_id, object_type, target_name
            )
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

        connection = await tm1_integration_service.get_connection(
            db, change.connection_id, change.organization_id
        )
        client = await self._client(db, connection)

        change.executed_by = executed_by
        change.executed_at = datetime.now(timezone.utc)

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

        else:  # delete_process
            base = await process_service.get_process_body(
                client, connection.id, change.target_name
            )
            change.previous_content = {"process": base}

            await process_service.delete_process(
                client, connection.id, change.target_name
            )

        change.status = "executed"

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
        except TM1ConnectionError as exc:
            change.status = "failed"
            change.execution_result = {"success": False, "status": "NoResponse"}
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

        return await tm1_change_repository.update(db, change)


change_service = ChangeService()
