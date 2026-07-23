import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.metadata import dependency_analyzer


async def _check_permission(db: AsyncSession, user_id: uuid.UUID) -> None:
    if not await auth_repository.user_has_permission(db, user_id, "tm1.read"):
        raise PermissionDeniedException("You do not have permission to read TM1 data.")


_OBJECT_TYPE_SCHEMA = {
    "type": "string",
    "enum": ["cube", "dimension", "hierarchy", "process", "chore"],
    "description": "The type of the object.",
}


class FindDependentsTool(Tool):

    name = "find_dependents"
    description = (
        "Find everything that transitively depends on a TM1 object, "
        "walking the metadata graph multiple hops (e.g. which chores "
        "eventually run because of this process). Requires metadata "
        "extraction to have been run for the connection first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "object_type": _OBJECT_TYPE_SCHEMA,
            "name": {
                "type": "string",
                "description": (
                    "The name of the object. Hierarchies use the "
                    "'Dimension:Hierarchy' qualified name."
                ),
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum number of hops to traverse (default 10).",
            },
        },
        "required": ["connection_id", "object_type", "name"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await _check_permission(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        object_type = str(kwargs["object_type"])
        name = str(kwargs["name"])
        max_depth = int(kwargs.get("max_depth", 10))

        dependents = await dependency_analyzer.find_dependents(
            db, connection_id, organization_id, object_type, name, max_depth=max_depth
        )

        return json.dumps({"object_type": object_type, "name": name, "dependents": dependents})


class FindDependenciesTool(Tool):

    name = "find_dependencies"
    description = (
        "Find everything a TM1 object transitively depends on, walking the "
        "metadata graph multiple hops (e.g. show everything downstream of "
        "this process). Requires metadata extraction to have been run for "
        "the connection first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "object_type": _OBJECT_TYPE_SCHEMA,
            "name": {
                "type": "string",
                "description": (
                    "The name of the object. Hierarchies use the "
                    "'Dimension:Hierarchy' qualified name."
                ),
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum number of hops to traverse (default 10).",
            },
        },
        "required": ["connection_id", "object_type", "name"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await _check_permission(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        object_type = str(kwargs["object_type"])
        name = str(kwargs["name"])
        max_depth = int(kwargs.get("max_depth", 10))

        dependencies = await dependency_analyzer.find_dependencies(
            db, connection_id, organization_id, object_type, name, max_depth=max_depth
        )

        return json.dumps(
            {"object_type": object_type, "name": name, "dependencies": dependencies}
        )


class DependencyPathTool(Tool):

    name = "dependency_path"
    description = (
        "Find the shortest dependency path from one TM1 object to another "
        "(e.g. is Cube A affected by TI Process B?). Returns found=false "
        "if no path exists within max_depth. Requires metadata extraction "
        "to have been run for the connection first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "from_type": _OBJECT_TYPE_SCHEMA,
            "from_name": {"type": "string", "description": "The source object's name."},
            "to_type": _OBJECT_TYPE_SCHEMA,
            "to_name": {"type": "string", "description": "The target object's name."},
            "max_depth": {
                "type": "integer",
                "description": "Maximum number of hops to search (default 10).",
            },
        },
        "required": ["connection_id", "from_type", "from_name", "to_type", "to_name"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await _check_permission(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        max_depth = int(kwargs.get("max_depth", 10))

        path = await dependency_analyzer.dependency_path(
            db,
            connection_id,
            organization_id,
            str(kwargs["from_type"]),
            str(kwargs["from_name"]),
            str(kwargs["to_type"]),
            str(kwargs["to_name"]),
            max_depth=max_depth,
        )

        return json.dumps({"found": path is not None, "path": path or []})


class FindUnusedObjectsTool(Tool):

    name = "find_unused_objects"
    description = (
        "Find TM1 objects that appear in zero relationships in the "
        "metadata graph — orphan cubes, unused dimensions, processes "
        "nothing runs, chores that reference nothing live. Requires "
        "metadata extraction to have been run for the connection first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "object_type": {
                "type": "string",
                "enum": ["cube", "dimension", "hierarchy", "process", "chore"],
                "description": "Optional: restrict to one object type.",
            },
        },
        "required": ["connection_id"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await _check_permission(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        object_type = kwargs.get("object_type")
        object_type = str(object_type) if object_type is not None else None

        unused = await dependency_analyzer.find_unused_objects(
            db, connection_id, organization_id, object_type
        )

        return json.dumps({"unused": unused})
