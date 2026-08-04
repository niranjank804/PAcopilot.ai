import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.functions import lookup, search, validate_code


class LookupTM1FunctionTool(Tool):

    name = "lookup_tm1_function"
    description = (
        "Look up TM1 functions in the reference library to confirm a function "
        "exists, what it does, whether it is valid in TI or in Rules, and which "
        "server versions support it. Use this before writing a function you are "
        "not certain about — a Rules-only function used in TI will not compile, "
        "and a v11-only function fails at runtime on a v12 (Planning Analytics "
        "SaaS) server. Accepts an exact function name or a keyword to search for."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "An exact function name (e.g. 'DimensionElementInsert') or a "
                    "keyword to search names and descriptions (e.g. 'attribute')."
                ),
            },
        },
        "required": ["query"],
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

        raw_query = kwargs.get("query")

        if raw_query is None or not str(raw_query).strip():
            return json.dumps(
                {
                    "error": (
                        "No query supplied. Pass a function name or a keyword "
                        "to search for."
                    )
                }
            )

        query = str(raw_query).strip()

        exact = lookup(query)

        if exact is not None:
            return json.dumps({"query": query, "match": exact.as_dict()})

        matches = search(query)

        if not matches:
            return json.dumps(
                {
                    "query": query,
                    "matches": [],
                    "note": (
                        f"No documented TM1 function matches '{query}'. The "
                        "library covers public TM1 functions, so treat this as "
                        "'not found in the reference' rather than proof the "
                        "function does not exist — verify before relying on it."
                    ),
                }
            )

        return json.dumps(
            {"query": query, "matches": [match.as_dict() for match in matches]}
        )


class CheckTM1CodeTool(Tool):

    name = "check_tm1_code"
    description = (
        "Check a block of TurboIntegrator or rule code for function-usage "
        "problems before proposing it: functions used in the wrong context "
        "(a Rules-only function inside TI, or vice versa) and functions that "
        "do not exist on the target server version. For rule and feeder code "
        "it also warns about function names it does not recognise, which is "
        "the only pre-execution check available there — TM1 cannot compile a "
        "rule without saving it. Returns an empty issue list when nothing is "
        "wrong. Errors are raised only for functions it can positively "
        "identify; unrecognised names are warnings to verify, not proof of a "
        "mistake."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The TI or rule source to check.",
            },
            "context": {
                "type": "string",
                "enum": ["TI", "Rules"],
                "description": (
                    "'TI' for TurboIntegrator process code, 'Rules' for cube "
                    "rule or feeder code."
                ),
            },
            "version": {
                "type": "string",
                "enum": ["v11", "v12"],
                "description": (
                    "Target server version, when known. Planning Analytics SaaS "
                    "is v12. Omit if unknown — version checks are then skipped."
                ),
            },
        },
        "required": ["code", "context"],
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

        raw_code = kwargs.get("code")

        # Returning "no issues" for absent code would read as a clean bill of
        # health for code that was never checked.
        if raw_code is None or not str(raw_code).strip():
            return json.dumps(
                {
                    "error": (
                        "No code supplied, so nothing was checked. Pass the TI "
                        "or rule source in the 'code' field."
                    )
                }
            )

        code = str(raw_code)
        context = str(kwargs.get("context") or "TI")
        version = kwargs.get("version")

        try:
            issues = validate_code(
                code,
                context=context,
                version=str(version) if version else None,
                # Rules and feeders get no compile check from TM1, so an
                # unrecognised function there would otherwise surface only when
                # a human executes the change. TI drafts are compiled against
                # the server, which already rejects invented names.
                report_unknown=(context == "Rules"),
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if not issues:
            return json.dumps(
                {
                    "context": context,
                    "version": version,
                    "issues": [],
                    "note": (
                        "No function-usage problems found. This checks function "
                        "context and version only — it is not a full compile."
                    ),
                }
            )

        return json.dumps(
            {"context": context, "version": version, "issues": issues}
        )
