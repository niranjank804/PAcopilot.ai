import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.ai.tools.tm1._common import (
    CONNECTION_ID_SCHEMA,
    TM1Tool,
    connection_id_of,
    evidence,
    required_text,
)
from src.core.exceptions import PermissionDeniedException, ValidationException
from src.repositories.auth_repository import auth_repository
from src.tm1.rules.analysis import trace_cell
from src.tm1.service import tm1_integration_service
from src.tm1.services import cell_service, cube_service


class ExecuteMDXTool(Tool):

    name = "execute_mdx"
    description = (
        "Execute a read-only MDX query against a TM1 cube and return cell "
        "values as a flat map of element-path to value. Always confirm real "
        "cube, dimension, and element names with other tools first — never "
        "guess member names, they rarely match natural-language phrasing "
        "exactly. Results are capped at 500 cells; narrow the query (e.g. "
        "add a WHERE clause) if you need a smaller slice."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "mdx": {
                "type": "string",
                "description": "The MDX query to execute.",
            },
        },
        "required": ["connection_id", "mdx"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        mdx = str(kwargs["mdx"])

        result = await tm1_integration_service.execute_mdx(
            db, connection_id, organization_id, mdx
        )

        return json.dumps({"cells": result.cells, "cell_count": len(result.cells)})


# ----------------------------------------------------------------------
# Coordinate reads. Distinct from execute_mdx: the model names cells, the
# application writes the MDX, and TM1 reports its own cell properties.
# ----------------------------------------------------------------------

_COORDINATE_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "One element per cube dimension, in the cube's dimension order "
        "(get_cube lists it)."
    ),
}


def _coordinates(kwargs: dict) -> list[list[str]]:
    raw = kwargs.get("coordinates")

    if not isinstance(raw, list) or not raw:
        raise ValidationException("coordinates must be a non-empty list of element lists.")

    if len(raw) > cell_service.MAX_COORDINATES:
        raise ValidationException(
            f"At most {cell_service.MAX_COORDINATES} coordinates per call."
        )

    coordinates = []

    for item in raw:
        if not isinstance(item, list) or not item:
            raise ValidationException("Each coordinate must be a list of element names.")
        coordinates.append([str(element) for element in item])

    return coordinates


def _refused(result: dict, cube: str) -> str | None:
    if "error" in result:
        return json.dumps({"cube": cube, "dimensions": result["dimensions"], "error": result["error"]})

    if "invalid" in result:
        return json.dumps(
            {
                "cube": cube,
                "dimensions": result["dimensions"],
                "invalid_elements": result["invalid"],
                "message": (
                    "These elements do not exist in the named dimension, so the "
                    "intersection is invalid. Nothing was read. Confirm names "
                    "with search_model_objects."
                ),
                "evidence": evidence(verified=["Element existence checked on the TM1 server"]),
            }
        )

    return None


class GetCellValuesTool(TM1Tool):

    name = "get_cell_values"
    description = (
        "Read specific cells by coordinate — one element per dimension — "
        "and, when several are given, compare them. Returns each value with "
        "TM1's own flags for whether it is rule-calculated or a "
        "consolidation. An element that does not exist is reported by name "
        "instead of being read as zero. Prefer this over execute_mdx when "
        f"the cells are known. At most {50} coordinates."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {"type": "string", "description": "The cube."},
            "coordinates": {
                "type": "array",
                "items": _COORDINATE_SCHEMA,
                "description": "Cells to read.",
            },
        },
        "required": ["connection_id", "cube_name", "coordinates"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        cube = required_text(kwargs, "cube_name")
        coordinates = _coordinates(kwargs)

        result = await tm1_integration_service.run(
            db, connection_id_of(kwargs), organization_id,
            cell_service.read_cells, cube, coordinates,
        )

        refused = _refused(result, cube)
        if refused:
            return refused

        cells = result["cells"]
        numeric = [c["value"] for c in cells if isinstance(c["value"], (int, float))]
        comparison = None

        if len(cells) > 1 and len(numeric) == len(cells):
            base = numeric[0]
            comparison = {
                "baseline": cells[0]["coordinates"],
                "differences": [
                    {
                        "coordinates": cell["coordinates"],
                        "value": cell["value"],
                        "difference": cell["value"] - base,
                        "percent": (
                            round((cell["value"] - base) / base * 100, 4) if base else None
                        ),
                    }
                    for cell in cells[1:]
                ],
            }

        return json.dumps(
            {
                "cube": cube,
                "dimensions": result["dimensions"],
                "cells": cells,
                "comparison": comparison,
                "evidence": evidence(
                    verified=["Values and cell properties read live from TM1 REST"],
                    inferred=["Differences are computed by PA-Copilot from those values"] if comparison else [],
                ),
            },
            default=str,
        )


class InspectCellTool(TM1Tool):

    name = "inspect_cell"
    description = (
        "Explain one cell: its value, whether TM1 says it is rule-derived, "
        "a consolidation or updateable (read from TM1, so verified), and "
        "which rule statement applies to it and whether that statement is "
        "fed (from PA-Copilot's rule parser, so analysis). Use this for "
        "'why is this number what it is' before reading rules by hand."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {"type": "string", "description": "The cube."},
            "elements": _COORDINATE_SCHEMA,
        },
        "required": ["connection_id", "cube_name", "elements"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        cube = required_text(kwargs, "cube_name")
        elements = [str(e) for e in (kwargs.get("elements") or [])]

        if not elements:
            raise ValidationException("elements must name one element per dimension.")

        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )

        result = await cell_service.read_cells(client, connection.id, cube, [elements])

        refused = _refused(result, cube)
        if refused:
            return refused

        cell = result["cells"][0]
        rules = await cube_service.get_cube_rules(client, connection.id, cube)
        trace = trace_cell(rules, elements) if rules else None

        verified = [
            "Value and RuleDerived / Consolidated / Updateable flags read from TM1",
        ]
        inferred: list[str] = []
        unknown: list[str] = []

        if cell["rule_derived"] and trace and not trace.get("calculated"):
            unknown.append(
                "TM1 reports the cell as rule-derived but no statement's area "
                "matches by literal elements; the applying statement likely "
                "uses a consolidation, an attribute or a DB() target the "
                "static parser cannot resolve"
            )
        elif trace and trace.get("calculated"):
            inferred.append(
                "The applying statement is the first calculation whose area "
                "contains every element of the cell, as TM1 evaluates rules"
            )

        unknown.append("Whether the cell is actually fed at runtime: TM1 REST does not expose feeder state")

        return json.dumps(
            {
                "cube": cube,
                "coordinates": cell["coordinates"],
                "value": cell["value"],
                "tm1": {
                    "rule_derived": cell["rule_derived"],
                    "consolidated": cell["consolidated"],
                    "updateable": cell["updateable"],
                },
                "rule_trace": trace,
                "has_rules": bool(rules),
                "evidence": evidence(verified=verified, inferred=inferred, unknown=unknown),
            },
            default=str,
        )
