import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.ti.learning import get_conventions
from src.tm1.ti.patterns import PATTERNS


class GetCodingStandardsTool(Tool):

    name = "get_coding_standards"
    description = (
        "Retrieve the coding conventions measured from this organization's own "
        "TurboIntegrator processes — naming, parameter prefixes, comment "
        "placement, error handling, and cleanup habits — together with the "
        "evidence for each. Call this before writing or reviewing TI, rule, or "
        "feeder code so that generated code matches how this team already "
        "writes it rather than generic TM1 style. Each convention reports how "
        "many processes follow it, so you can cite the evidence and can tell a "
        "strong house rule from a weak tendency. Returns an empty list when no "
        "processes have been analysed yet; say so rather than inventing "
        "standards."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "minimum_confidence": {
                "type": "number",
                "description": (
                    "Only return conventions at or above this confidence "
                    "(0 to 1). Defaults to 0.6, which excludes weak tendencies."
                ),
            },
        },
        "required": [],
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

        raw_threshold = kwargs.get("minimum_confidence")

        try:
            threshold = 0.6 if raw_threshold is None else float(raw_threshold)
        except (TypeError, ValueError):
            threshold = 0.6

        threshold = min(max(threshold, 0.0), 1.0)

        conventions = await get_conventions(db, organization_id=organization_id)
        selected = [c for c in conventions if c.confidence >= threshold]

        if not selected:
            return json.dumps(
                {
                    "conventions": [],
                    "note": (
                        "No coding conventions have been learned for this "
                        "organization yet, either because no TurboIntegrator "
                        "processes have been analysed or because none reached "
                        "the confidence threshold. Follow documented IBM "
                        "Planning Analytics practice and say that you are doing "
                        "so — do not present generic style as this team's."
                    ),
                    "known_patterns": [p.key for p in PATTERNS],
                }
            )

        return json.dumps(
            {
                "conventions": [
                    {
                        "key": c.convention_key,
                        "statement": c.statement,
                        "confidence": round(c.confidence, 3),
                        "evidence": (
                            f"{c.support} of {c.sample} analysed processes"
                        ),
                        "examples": c.examples[:5],
                        "counter_examples": c.counter_examples[:3],
                    }
                    for c in selected
                ],
                "note": (
                    "These are measured from this organization's own processes. "
                    "Follow them when generating code, and cite the evidence if "
                    "asked why. Where a convention conflicts with documented IBM "
                    "practice, say so rather than silently picking one."
                ),
            }
        )
