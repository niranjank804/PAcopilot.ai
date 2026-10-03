"""Validate and review TurboIntegrator code without saving it.

`validate_process_code` asks the TM1 server to compile code that exists
only in memory — TM1's `/CompileProcess` action, which does not save —
and runs the same static checks a draft gets. It is how a proposed fix, a
local file or a snippet is checked against the real server before anyone
proposes it as a change.

`review_process_code` is the deterministic review in `tm1/ti/review.py`:
syntax, v11/v12 compatibility, destructive operations, complexity,
maintainability, naming and documentation, each finding with its
evidence and a confidence. It reviews a live process or supplied text
(for example a `.pro` attached to the chat).

Neither changes anything on the server.
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.tm1._common import (
    CONNECTION_ID_SCHEMA,
    TM1Tool,
    connection_id_of,
    evidence,
    required_text,
)
from src.tm1.deployment import ti_analysis
from src.tm1.deployment.change_service import build_candidate
from src.tm1.functions import validate_process as validate_functions
from src.tm1.service import tm1_integration_service
from src.tm1.services import process_service
from src.tm1.ti.parser import SECTIONS, parse_process_code
from src.tm1.ti.review import review

_CODE_PROPERTIES = {
    section: {"type": "string", "description": f"{section.capitalize()} code."}
    for section in SECTIONS
}

_VERSION_PROPERTY = {
    "type": "string",
    "enum": ["v11", "v12"],
    "description": "Check function availability against this TM1 version.",
}


def _supplied_code(kwargs: dict) -> dict:
    return {s: str(kwargs[s]) for s in SECTIONS if kwargs.get(s) is not None}


def _base_declarations(base: dict | None) -> tuple[list[dict], list[dict]]:
    """Parameters and variables of the server's version, in the lowercase
    shape the analysers read."""

    if not base:
        return [], []

    parameters = [
        {
            "name": p.get("Name", ""),
            "type": p.get("Type", ""),
            "default": p.get("Value"),
            "prompt": p.get("Prompt", ""),
        }
        for p in (base.get("Parameters") or [])
        if isinstance(p, dict)
    ]
    variables = [
        {"name": v.get("Name", ""), "type": v.get("Type", "")}
        for v in (base.get("Variables") or [])
        if isinstance(v, dict)
    ]

    return parameters, variables


class ValidateProcessCodeTool(TM1Tool):

    name = "validate_process_code"
    description = (
        "Compile TurboIntegrator code on the TM1 server WITHOUT saving it, "
        "and run the static checks a draft gets (undefined variables, "
        "casing, functions used in the wrong context or missing on the "
        "target version). Give the process name and the tabs you changed; "
        "tabs you omit are taken from the server's version, and so are its "
        "parameters, variables and datasource. Use this to check a fix or a "
        "local file before proposing it. Nothing on the server changes."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {
                "type": "string",
                "description": "The process the code belongs to (it need not exist yet).",
            },
            **_CODE_PROPERTIES,
            "version": _VERSION_PROPERTY,
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        name = required_text(kwargs, "process_name")
        version = kwargs.get("version") if kwargs.get("version") in ("v11", "v12") else None
        supplied = _supplied_code(kwargs)

        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )

        exists = await process_service.process_exists(client, connection.id, name)
        base = (
            await process_service.get_process_body(client, connection.id, name)
            if exists
            else None
        )
        parameters, variables = _base_declarations(base)

        candidate = build_candidate(name, supplied, base)
        compile_errors = await process_service.compile_process_dryrun(
            client, connection.id, candidate
        )

        sections = {
            "prolog": candidate.prolog_procedure or "",
            "metadata": candidate.metadata_procedure or "",
            "data": candidate.data_procedure or "",
            "epilog": candidate.epilog_procedure or "",
        }
        static_errors = ti_analysis.analyze(
            {**sections, "parameters": parameters, "variables": variables},
            datasource_type=(base or {}).get("DataSourceType"),
        )
        function_issues = validate_functions(sections, version=version)
        blocking = [i for i in function_issues if i["severity"] == "error"]

        valid = not compile_errors and not static_errors and not blocking

        return json.dumps(
            {
                "process": name,
                "existing_process": exists,
                "saved": False,
                "valid": valid,
                "server_compile": {
                    "ok": not compile_errors,
                    "errors": compile_errors or [],
                },
                "static_errors": static_errors,
                "function_issues": function_issues,
                "tabs_checked": sorted(supplied) or ["(server version, unchanged)"],
                "evidence": evidence(
                    verified=[
                        "Compiled by the TM1 server (/CompileProcess, not saved)",
                        "Static analysis and the TM1 function reference",
                    ],
                    unknown=[
                        "Compilation does not run the code: data errors, missing "
                        "files and wrong element names surface only at run time",
                    ],
                ),
            },
            default=str,
        )


class ReviewProcessCodeTool(TM1Tool):

    name = "review_process_code"
    description = (
        "Review a TurboIntegrator process and return findings, each with "
        "severity, object, evidence, reason, recommendation and confidence: "
        "syntax problems, functions missing on the target TM1 version (v12 "
        "readiness), destructive operations (CubeClearData, "
        "DimensionDeleteAllElements, ExecuteCommand …), complexity, missing "
        "error handling, temporary objects left behind, commented-out code, "
        "missing header comment or parameter prompts, inconsistent parameter "
        "prefixes. Reviews the live process, or code you supply (for example "
        "a .pro file the user attached)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {"type": "string", "description": "The process to review."},
            **_CODE_PROPERTIES,
            "version": _VERSION_PROPERTY,
        },
        "required": ["connection_id", "process_name"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        name = required_text(kwargs, "process_name")
        version = kwargs.get("version") if kwargs.get("version") in ("v11", "v12") else None
        supplied = _supplied_code(kwargs)

        if supplied:
            # Supplied code is reviewed as given. The server's parameters
            # and variables are borrowed when the process exists, so a
            # declared parameter is not reported as undefined.
            connection, client = await tm1_integration_service.connect(
                db, connection_id_of(kwargs), organization_id
            )
            exists = await process_service.process_exists(client, connection.id, name)
            base = (
                await process_service.get_process_body(client, connection.id, name)
                if exists
                else None
            )
            parameters, variables = _base_declarations(base)
            record = parse_process_code(
                name,
                **supplied,
                datasource_type=str((base or {}).get("DataSourceType") or "none"),
                parameters=parameters,
                variables=variables,
            )
            source = "supplied code"
        else:
            process = await tm1_integration_service.get_process(
                db, connection_id_of(kwargs), organization_id, name
            )
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
            source = "live process"

        findings, metrics = review(record, version=version)
        counts = {
            level: sum(1 for f in findings if f.severity == level)
            for level in ("error", "warning", "info")
        }

        return json.dumps(
            {
                "process": name,
                "reviewed": source,
                "target_version": version,
                "counts": counts,
                "metrics": metrics,
                "findings": [f.to_dict() for f in findings],
                "evidence": evidence(
                    verified=[
                        f"Code of the {source}",
                        "Findings from PA-Copilot's TI parser, static analyser and TM1 function reference",
                    ],
                    unknown=[
                        "Whether the business logic is correct: not judged here",
                        "Behaviour on real data: only a run shows it",
                    ],
                ),
            },
            default=str,
        )
