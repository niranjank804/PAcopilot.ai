"""Rule and feeder intelligence tools.

These do analysis, not retrieval. `get_cube_rules` hands the model rule text
and asks it to reason; these run a static analyser over the parsed rule and
return findings with line numbers and severities.

The difference matters most for feeders. Reasoning over rule text spots a
missing feeder in a three-line rule and misses it in a three-hundred-line
one, and feeders are exactly where a wrong answer is invisible: the rule is
right, the leaf is right, and only the consolidation is zero.
"""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.rules.analysis import analyze_rules, trace_cell
from src.tm1.service import tm1_integration_service

CONNECTION_ID_SCHEMA = {
    "type": "string",
    "description": "The ID of the TM1 connection to query.",
}

# A model-wide audit is one round trip per cube with a rule. Bounded so a
# large model cannot turn a single tool call into a hundred requests.
MAX_AUDIT_CUBES = 40

# How many cubes to read at once during an audit.
AUDIT_CONCURRENCY = 5


class _RuleTool(Tool):

    required_permission = "tm1.read"

    async def _authorize(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )


class AnalyzeCubeRulesTool(_RuleTool):

    name = "analyze_cube_rules"
    description = (
        "Statically analyse a cube's rules and feeders and return findings "
        "with severities and line numbers. Detects unfed calculations under "
        "SKIPCHECK (the classic cause of a correct leaf value with a zero "
        "total), feeders declared without SKIPCHECK, statements stranded "
        "below the FEEDERS marker, and rule areas shadowed by an earlier "
        "statement. Prefer this over reading rule text when the question is "
        "whether the rules are correct."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {
                "type": "string",
                "description": "The cube whose rules should be analysed.",
            },
        },
        "required": ["connection_id", "cube_name"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await self._authorize(db, user_id)

        cube_name = str(kwargs["cube_name"])
        rules = await tm1_integration_service.get_cube_rules(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            cube_name,
        )

        if not rules:
            return json.dumps(
                {
                    "cube": cube_name,
                    "has_rules": False,
                    "message": "This cube has no rules.",
                }
            )

        report = analyze_rules(rules)
        return json.dumps({"cube": cube_name, "has_rules": True, **report})


class TraceCellCalculationTool(_RuleTool):

    name = "trace_cell_calculation"
    description = (
        "Explain how one cell intersection gets its value: which rule "
        "statement applies to it, whether an earlier statement shadows it, "
        "and whether anything feeds it. Use this to answer 'why is this "
        "number wrong' or 'where does this value come from' for a specific "
        "intersection."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {
                "type": "string",
                "description": "The cube containing the cell.",
            },
            "elements": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The element names identifying the cell, in any order, "
                    "for example ['Gross Margin', 'EMEA', 'Jan']."
                ),
            },
        },
        "required": ["connection_id", "cube_name", "elements"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await self._authorize(db, user_id)

        cube_name = str(kwargs["cube_name"])
        elements = [str(e) for e in (kwargs.get("elements") or [])]

        if not elements:
            return json.dumps({"error": "elements must not be empty."})

        rules = await tm1_integration_service.get_cube_rules(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            cube_name,
        )

        if not rules:
            return json.dumps(
                {
                    "cube": cube_name,
                    "calculated": False,
                    "message": "This cube has no rules, so the value is "
                    "stored data or a plain consolidation.",
                }
            )

        return json.dumps({"cube": cube_name, **trace_cell(rules, elements)})


class SearchRulesTool(_RuleTool):

    name = "search_rules"
    description = (
        "Find every cube whose rule text contains a given string, across the "
        "whole model. Use this to answer questions like 'which cubes "
        "reference this dimension in a rule' or 'where is this DB() lookup "
        "used'. Matching happens on the server and ignores case and spacing."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "search_string": {
                "type": "string",
                "description": "Text to look for in rule statements.",
            },
        },
        "required": ["connection_id", "search_string"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        await self._authorize(db, user_id)

        search_string = str(kwargs["search_string"]).strip()
        if not search_string:
            return json.dumps({"error": "search_string must not be empty."})

        cubes = await tm1_integration_service.search_rule_substring(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            search_string,
        )

        return json.dumps(
            {
                "search_string": search_string,
                "match_count": len(cubes),
                "cubes": cubes,
            }
        )


class AuditModelRulesTool(_RuleTool):

    name = "audit_model_rules"
    description = (
        "Analyse the rules of EVERY cube in the model and return the cubes "
        "with problems, worst first. Use this for a health check, before a "
        "release, or when a number is wrong somewhere but you do not know "
        f"which cube. Reads at most {MAX_AUDIT_CUBES} cubes in one call."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "severity": {
                "type": "string",
                "enum": ["critical", "warning", "info"],
                "description": (
                    "Lowest severity to report. Defaults to 'warning', which "
                    "includes critical findings."
                ),
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

        await self._authorize(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        threshold = str(kwargs.get("severity") or "warning")
        keep = {
            "critical": {"critical"},
            "warning": {"critical", "warning"},
            "info": {"critical", "warning", "info"},
        }.get(threshold, {"critical", "warning"})

        cube_names = await tm1_integration_service.list_cubes_with_rules(
            db, connection_id, organization_id
        )
        truncated = len(cube_names) > MAX_AUDIT_CUBES
        cube_names = cube_names[:MAX_AUDIT_CUBES]

        semaphore = asyncio.Semaphore(AUDIT_CONCURRENCY)

        async def analyse(cube_name: str) -> dict | None:
            async with semaphore:
                try:
                    rules = await tm1_integration_service.get_cube_rules(
                        db, connection_id, organization_id, cube_name
                    )
                except Exception as exc:  # noqa: BLE001
                    # One unreadable cube must not sink the whole audit.
                    return {
                        "cube": cube_name,
                        "error": f"{type(exc).__name__}: {exc}",
                        "findings": [],
                        "critical": 0,
                        "warning": 0,
                    }

            if not rules:
                return None

            report = analyze_rules(rules)
            findings = [
                f for f in report["findings"] if f["severity"] in keep
            ]
            if not findings:
                return None

            return {
                "cube": cube_name,
                "critical": report["summary"]["critical"],
                "warning": report["summary"]["warning"],
                "findings": findings,
            }

        results = await asyncio.gather(*(analyse(name) for name in cube_names))
        affected = [r for r in results if r]
        affected.sort(key=lambda r: (-r["critical"], -r["warning"], r["cube"]))

        return json.dumps(
            {
                "cubes_analysed": len(cube_names),
                "cubes_with_findings": len(affected),
                "total_critical": sum(r["critical"] for r in affected),
                "truncated": truncated,
                "note": (
                    f"Only the first {MAX_AUDIT_CUBES} cubes with rules were "
                    "analysed."
                    if truncated
                    else None
                ),
                "results": affected,
            }
        )
