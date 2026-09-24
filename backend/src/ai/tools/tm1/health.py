"""Whole-model health check.

This is the capability a retrieval surface cannot reach. Answering "is this
model healthy" by fetching objects one at a time means dozens of round trips
with the model holding a running tally in its head - so in practice nobody
asks, and the unfed rule in the thirty-fourth cube stays there.

Here it is one call. Rule and feeder analysis across every cube that has a
rule, TurboIntegrator static analysis across every process, both bounded and
run concurrently, returned ranked worst-first.

The analyses are the same ones used elsewhere - `tm1.rules.analysis` and
`deployment.ti_analysis` - so a finding here and a finding on a draft agree
with each other.
"""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.deployment import ti_analysis
from src.tm1.rules.analysis import analyze_rules
from src.tm1.service import tm1_integration_service

MAX_CUBES = 40
MAX_PROCESSES = 60
CONCURRENCY = 5


class RunModelHealthCheckTool(Tool):

    name = "run_model_health_check"
    description = (
        "Audit the whole model in one call: rule and feeder analysis across "
        "every cube that has rules, plus static analysis of every "
        "TurboIntegrator process. Returns problems ranked worst-first with "
        "counts. Use this before a release, during a handover, or when "
        "something is wrong somewhere but you do not know where. Reads at "
        f"most {MAX_CUBES} cubes and {MAX_PROCESSES} processes."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to audit.",
            },
            "include_processes": {
                "type": "boolean",
                "description": (
                    "Analyse TI processes as well as rules. Default true. "
                    "Set false for a faster, rules-only check."
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

        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        include_processes = kwargs.get("include_processes", True)
        semaphore = asyncio.Semaphore(CONCURRENCY)

        cube_report, process_report = await asyncio.gather(
            self._audit_rules(db, connection_id, organization_id, semaphore),
            self._audit_processes(db, connection_id, organization_id, semaphore)
            if include_processes
            else _empty_process_report(),
        )

        critical = sum(c["critical"] for c in cube_report["cubes"])
        warnings = sum(c["warning"] for c in cube_report["cubes"])
        process_issues = sum(len(p["issues"]) for p in process_report["processes"])

        return json.dumps(
            {
                "verdict": _verdict(critical, warnings, process_issues),
                "totals": {
                    "cubes_analysed": cube_report["analysed"],
                    "cubes_with_findings": len(cube_report["cubes"]),
                    "critical_rule_findings": critical,
                    "warning_rule_findings": warnings,
                    "processes_analysed": process_report["analysed"],
                    "processes_with_issues": len(process_report["processes"]),
                    "process_issues": process_issues,
                },
                "truncated": {
                    "cubes": cube_report["truncated"],
                    "processes": process_report["truncated"],
                },
                "rules": cube_report["cubes"],
                "processes": process_report["processes"],
            }
        )

    async def _audit_rules(
        self, db, connection_id, organization_id, semaphore
    ) -> dict:
        names = await tm1_integration_service.list_cubes_with_rules(
            db, connection_id, organization_id
        )
        truncated = len(names) > MAX_CUBES
        names = names[:MAX_CUBES]

        async def one(cube_name: str) -> dict | None:
            async with semaphore:
                try:
                    rules = await tm1_integration_service.get_cube_rules(
                        db, connection_id, organization_id, cube_name
                    )
                except Exception as exc:  # noqa: BLE001
                    return {
                        "cube": cube_name,
                        "critical": 0,
                        "warning": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                        "findings": [],
                    }

            if not rules:
                return None

            report = analyze_rules(rules)
            if not report["findings"]:
                return None

            return {
                "cube": cube_name,
                "critical": report["summary"]["critical"],
                "warning": report["summary"]["warning"],
                "findings": report["findings"],
            }

        results = [r for r in await asyncio.gather(*map(one, names)) if r]
        results.sort(key=lambda r: (-r["critical"], -r["warning"], r["cube"]))

        return {"analysed": len(names), "truncated": truncated, "cubes": results}

    async def _audit_processes(
        self, db, connection_id, organization_id, semaphore
    ) -> dict:
        names = await tm1_integration_service.list_processes(
            db, connection_id, organization_id
        )
        truncated = len(names) > MAX_PROCESSES
        names = names[:MAX_PROCESSES]

        async def one(process_name: str) -> dict | None:
            async with semaphore:
                try:
                    process = await tm1_integration_service.get_process(
                        db, connection_id, organization_id, process_name
                    )
                except Exception as exc:  # noqa: BLE001
                    return {
                        "process": process_name,
                        "issues": [f"{type(exc).__name__}: {exc}"],
                    }

            issues = ti_analysis.analyze(
                {
                    "prolog": process.prolog,
                    "metadata": process.metadata,
                    "data": process.data,
                    "epilog": process.epilog,
                    "parameters": [
                        {"Name": name} for name in (process.parameter_names or [])
                    ],
                },
                datasource_type=process.datasource_type,
            )

            if not issues:
                return None

            return {"process": process_name, "issues": issues[:10]}

        results = [r for r in await asyncio.gather(*map(one, names)) if r]
        results.sort(key=lambda r: (-len(r["issues"]), r["process"]))

        return {
            "analysed": len(names),
            "truncated": truncated,
            "processes": results,
        }


async def _empty_process_report() -> dict:
    return {"analysed": 0, "truncated": False, "processes": []}


def _verdict(critical: int, warnings: int, process_issues: int) -> str:
    if critical:
        return (
            f"{critical} critical rule finding(s). Consolidated values are "
            "very likely wrong right now."
        )
    if warnings or process_issues:
        return (
            f"No critical findings. {warnings} rule warning(s) and "
            f"{process_issues} process issue(s) worth reviewing."
        )
    return "No findings in the objects analysed."
