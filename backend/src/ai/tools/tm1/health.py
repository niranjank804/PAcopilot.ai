"""Whole-model health check.

This is the capability a retrieval surface cannot reach. Answering "is this
model healthy" by fetching objects one at a time means dozens of round trips
with the model holding a running tally in its head - so in practice nobody
asks, and the unfed rule in the thirty-fourth cube stays there.

Here it is one call. Rule and feeder analysis across every cube that has a
rule, the process review (`tm1/ti/review.py`: syntax, compatibility,
dangerous operations, complexity, maintainability, documentation) across
every process, both bounded and run concurrently, returned ranked
worst-first.

Every finding has the same shape — severity, object, evidence, reason,
recommendation, confidence — whether it came from a rule or a process, so
a report can be read and checked line by line. The analyses are the same
ones used elsewhere, so a finding here and a finding on a draft agree.

The connection is resolved once and the fan-out runs on the TM1 client:
concurrent queries on one database session are not permitted.
"""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.rules.analysis import analyze_rules
from src.tm1.service import tm1_integration_service
from src.tm1.services import cube_service, process_service
from src.tm1.ti.parser import parse_process_code
from src.tm1.ti.review import review

MAX_CUBES = 40
MAX_PROCESSES = 60
CONCURRENCY = 5
# Findings kept per object, worst first. The counts stay exact.
MAX_FINDINGS_PER_OBJECT = 10

# What to do about each rule finding code in src/tm1/rules/analysis.py,
# and how sure the static check can be. "medium" where the answer depends
# on resolving rule areas statically, which DB() and variable targets
# defeat.
RULE_GUIDANCE: dict[str, tuple[str, str]] = {
    "skipcheck_without_feeders": (
        "Add a FEEDERS; section feeding every N: calculation, or remove SKIPCHECK.",
        "high",
    ),
    "feeders_without_skipcheck": (
        "Add SKIPCHECK; at the top of the rule, or remove the unused FEEDERS section.",
        "high",
    ),
    "unfed_calculation": (
        "Add a feeder from a source of this calculation to its area.",
        "medium",
    ),
    "calculation_below_feeders": (
        "Move the statement above the FEEDERS; marker; below it TM1 reads it as a feeder.",
        "high",
    ),
    "string_rules_without_feedstrings": (
        "Add FEEDSTRINGS; so string cells are fed.",
        "high",
    ),
    "shadowed_area": (
        "Narrow or reorder the earlier statement; TM1 applies the first statement whose area matches.",
        "medium",
    ),
    "feeder_to_uncalculated_area": (
        "Remove or retarget the feeder; feeding a stored area only inflates the fed cell count.",
        "medium",
    ),
}


def rule_finding(cube_name: str, finding: dict) -> dict:
    """A rule-analysis finding in the shared shape."""

    recommendation, confidence = RULE_GUIDANCE.get(
        finding.get("code", ""), ("Review the statement.", "medium")
    )

    return {
        "severity": finding.get("severity"),
        "category": "rules",
        "object": f"cube:{cube_name}",
        "evidence": (
            f"line {finding['line_number']}: {finding.get('statement') or ''}".strip()
            if finding.get("line_number")
            else finding.get("statement") or finding.get("code")
        ),
        "reason": finding.get("message"),
        "recommendation": recommendation,
        "confidence": confidence,
        "code": finding.get("code"),
    }


class RunModelHealthCheckTool(Tool):

    name = "run_model_health_check"
    description = (
        "Audit the whole model in one call: rule and feeder analysis across "
        "every cube that has rules, plus a review of every TurboIntegrator "
        "process (syntax, v11/v12 compatibility, destructive operations, "
        "complexity, maintainability, documentation). Every finding has a "
        "severity, the object, the evidence, the reason, a recommendation "
        "and a confidence. Use this before a release, during a handover, or "
        "when something is wrong somewhere but you do not know where. Reads "
        f"at most {MAX_CUBES} cubes and {MAX_PROCESSES} processes."
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
                    "Review TI processes as well as rules. Default true. "
                    "Set false for a faster, rules-only check."
                ),
            },
            "target_version": {
                "type": "string",
                "enum": ["v11", "v12"],
                "description": (
                    "Check function compatibility against this TM1 version. "
                    "Use v12 for a v12-readiness sweep."
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
        version = kwargs.get("target_version")
        version = version if version in ("v11", "v12") else None

        connection, client = await tm1_integration_service.connect(
            db, connection_id, organization_id
        )
        semaphore = asyncio.Semaphore(CONCURRENCY)

        cube_report, process_report = await asyncio.gather(
            self._audit_rules(client, connection.id, semaphore),
            self._audit_processes(client, connection.id, semaphore, version)
            if include_processes
            else _empty_process_report(),
        )

        critical = sum(c["critical"] for c in cube_report["cubes"])
        warnings = sum(c["warning"] for c in cube_report["cubes"])
        process_issues = sum(p["finding_count"] for p in process_report["processes"])
        process_errors = sum(p["errors"] for p in process_report["processes"])

        return json.dumps(
            {
                "verdict": _verdict(critical, warnings, process_errors, process_issues),
                "totals": {
                    "cubes_analysed": cube_report["analysed"],
                    "cubes_with_findings": len(cube_report["cubes"]),
                    "critical_rule_findings": critical,
                    "warning_rule_findings": warnings,
                    "processes_analysed": process_report["analysed"],
                    "processes_with_issues": len(process_report["processes"]),
                    "process_issues": process_issues,
                    "process_errors": process_errors,
                },
                "target_version": version,
                "truncated": {
                    "cubes": cube_report["truncated"],
                    "processes": process_report["truncated"],
                },
                "rules": cube_report["cubes"],
                "processes": process_report["processes"],
                "evidence": {
                    "verified": [
                        "Rule text and process source read live from TM1 REST",
                    ],
                    "analysis": (
                        "Findings come from PA-Copilot's rule parser and TI "
                        "analysers, deterministically. Confidence 'medium' "
                        "marks checks that depend on resolving areas or "
                        "names statically."
                    ),
                    "not_checked": [
                        "Runtime feeder state (TM1 REST does not expose it)",
                        "Business correctness of calculations",
                    ],
                },
            }
        )

    async def _audit_rules(self, client, connection_id, semaphore) -> dict:
        names = await cube_service.list_cubes_with_rules(client, connection_id)
        truncated = len(names) > MAX_CUBES
        names = names[:MAX_CUBES]

        async def one(cube_name: str) -> dict | None:
            async with semaphore:
                try:
                    rules = await cube_service.get_cube_rules(
                        client, connection_id, cube_name
                    )
                except Exception as exc:  # noqa: BLE001
                    # One unreadable cube must not sink the whole audit.
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
                "findings": [
                    rule_finding(cube_name, f)
                    for f in report["findings"][:MAX_FINDINGS_PER_OBJECT]
                ],
            }

        results = [r for r in await asyncio.gather(*map(one, names)) if r]
        results.sort(key=lambda r: (-r["critical"], -r["warning"], r["cube"]))

        return {"analysed": len(names), "truncated": truncated, "cubes": results}

    async def _audit_processes(
        self, client, connection_id, semaphore, version
    ) -> dict:
        names = await process_service.list_processes(client, connection_id)
        truncated = len(names) > MAX_PROCESSES
        names = names[:MAX_PROCESSES]

        async def one(process_name: str) -> dict | None:
            async with semaphore:
                try:
                    process = await process_service.get_process(
                        client, connection_id, process_name
                    )
                except Exception as exc:  # noqa: BLE001
                    return {
                        "process": process_name,
                        "errors": 1,
                        "finding_count": 1,
                        "findings": [
                            {
                                "severity": "error",
                                "category": "access",
                                "object": f"process:{process_name}",
                                "evidence": f"{type(exc).__name__}: {exc}",
                                "reason": "The process could not be read.",
                                "recommendation": "Check the connection user's access to this process.",
                                "confidence": "high",
                            }
                        ],
                    }

            record = parse_process_code(
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
            findings, metrics = review(record, version=version)

            if not findings:
                return None

            return {
                "process": process_name,
                "errors": sum(1 for f in findings if f.severity == "error"),
                "finding_count": len(findings),
                "complexity": {
                    k: metrics[k] for k in ("lines", "statements", "loops", "max_nesting")
                },
                "findings": [f.to_dict() for f in findings[:MAX_FINDINGS_PER_OBJECT]],
            }

        results = [r for r in await asyncio.gather(*map(one, names)) if r]
        results.sort(key=lambda r: (-r["errors"], -r["finding_count"], r["process"]))

        return {
            "analysed": len(names),
            "truncated": truncated,
            "processes": results,
        }


async def _empty_process_report() -> dict:
    return {"analysed": 0, "truncated": False, "processes": []}


def _verdict(critical: int, warnings: int, process_errors: int, process_issues: int) -> str:
    if critical:
        return (
            f"{critical} critical rule finding(s). Consolidated values are "
            "very likely wrong right now."
        )
    if process_errors:
        return (
            f"No critical rule findings. {process_errors} process error(s) — "
            "code that will not compile or will not run on the target version."
        )
    if warnings or process_issues:
        return (
            f"No critical findings. {warnings} rule warning(s) and "
            f"{process_issues} process finding(s) worth reviewing."
        )
    return "No findings in the objects analysed."
