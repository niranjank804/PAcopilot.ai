import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from TM1py import Process

from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.database.models.tm1_change import TM1Change
from src.repositories.tm1_change_repository import tm1_change_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.exceptions import TM1NotFoundError
from src.tm1.metadata import dependency_analyzer
from src.tm1.service import tm1_integration_service
from src.tm1.services import cube_service, process_service

VALID_CHANGE_TYPES = (
    "update_rules",
    "create_process",
    "update_process",
    "delete_process",
)

_PROCESS_CODE_FIELDS = {
    "prolog": "prolog_procedure",
    "metadata": "metadata_procedure",
    "data": "data_procedure",
    "epilog": "epilog_procedure",
}


def _build_process(name: str, content: dict, base: dict | None = None) -> Process:
    if base:
        process = Process.from_dict(base)
        process.name = name
    else:
        process = Process(name=name)

    for key, attribute in _PROCESS_CODE_FIELDS.items():
        if key in content:
            setattr(process, attribute, content[key] or "")

    if "has_security_access" in content:
        process.has_security_access = bool(content["has_security_access"])

    return process


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
            errors = await process_service.compile_process_dryrun(
                client, connection.id, candidate
            )
            validation_errors = errors or []
            object_type = "process"

        else:  # delete_process
            exists = await process_service.process_exists(
                client, connection.id, target_name
            )
            if not exists:
                raise TM1NotFoundError(f"Process '{target_name}' not found.")
            object_type = "process"

        impact = await self._impact(
            db, connection.id, organization_id, object_type, target_name
        )

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

        return await tm1_change_repository.create(db, change)

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

    async def execute_change(
        self,
        db: AsyncSession,
        change: TM1Change,
        executed_by: uuid.UUID,
    ) -> TM1Change:

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

            errors = await cube_service.check_cube_rules(
                client, connection.id, change.target_name
            )

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

        elif change.change_type == "create_process":
            change.previous_content = {"existed": False}

            candidate = _build_process(change.target_name, change.new_content)
            await process_service.update_or_create_process(
                client, connection.id, candidate
            )

            errors = await process_service.compile_process_on_server(
                client, connection.id, change.target_name
            )

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

        elif change.change_type == "update_process":
            base = await process_service.get_process_body(
                client, connection.id, change.target_name
            )
            change.previous_content = {"process": base}

            candidate = _build_process(change.target_name, change.new_content, base)
            await process_service.update_or_create_process(
                client, connection.id, candidate
            )

            errors = await process_service.compile_process_on_server(
                client, connection.id, change.target_name
            )

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

    async def rollback_change(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> TM1Change:

        if change.status != "executed":
            raise ConflictException(
                f"Only executed changes can be rolled back (status: {change.status})."
            )

        connection = await tm1_integration_service.get_connection(
            db, change.connection_id, change.organization_id
        )
        client = await self._client(db, connection)

        if change.change_type == "update_rules":
            await cube_service.update_cube_rules(
                client, connection.id, change.target_name,
                change.previous_content.get("rules") or "",
            )

        elif change.change_type == "create_process":
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
