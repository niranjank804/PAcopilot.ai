"""Risk classification for provider tools. Owned by the application.

This is the load-bearing control of the whole phase.

An MCP server is a *remote, customer-configured* service. Its tool names
and descriptions are attacker-influenced input in exactly the way a
knowledge document is: a tool called `analyze_cube` whose description
says "also deletes stale views, always safe" is a plausible thing to
encounter, whether through compromise or through a vendor's careless
wording.

So three rules hold here, and the tests enforce all three:

1. **The model never classifies.** Risk comes from this module's rules
   applied to the tool name, never from the tool's own description and
   never from the LLM's opinion of it.

2. **Unknown means unusable.** A tool that matches no rule is
   `UNCLASSIFIED`, and `is_executable()` refuses it. A new IBM tool
   appearing in a future release therefore fails closed — it becomes
   visible in the inspector and inert, rather than silently callable.

3. **Descriptions are never consulted.** `classify()` does not take the
   description as an argument at all. That is deliberate: a parameter
   that does not exist cannot be misused by a later refactor.
"""

import re
from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    #: Reads metadata or data. Safe in this phase.
    READ = "READ"

    #: Computes over data (impact analysis, outlier detection). Reads
    #: only, but potentially expensive, so metered separately.
    ANALYSIS = "ANALYSIS"

    #: Writes under a constraint (a sandbox, a draft). Still a write.
    CONTROLLED_WRITE = "CONTROLLED_WRITE"

    #: Mutates model or data.
    WRITE = "WRITE"

    #: Irreversible or wide-blast-radius.
    DESTRUCTIVE = "DESTRUCTIVE"

    #: Matched no rule. Never executable.
    UNCLASSIFIED = "UNCLASSIFIED"


#: The only levels this phase permits. Everything else is discovered,
#: displayed, and blocked.
EXECUTABLE_RISK_LEVELS = frozenset({RiskLevel.READ, RiskLevel.ANALYSIS})


# Ordered most-dangerous-first: a name containing both "delete" and
# "get" must classify as DESTRUCTIVE, not READ. Matching the safest
# pattern first is the classic way this kind of table becomes a
# vulnerability.
_RULES: tuple[tuple[RiskLevel, re.Pattern[str]], ...] = (
    (
        RiskLevel.DESTRUCTIVE,
        re.compile(
            r"(delete|destroy|drop|purge|truncate|remove|reset|wipe|clear)",
            re.I,
        ),
    ),
    (
        RiskLevel.WRITE,
        re.compile(
            r"(create|modify|update|write|set_|put_|patch|rename|move|"
            r"publish|deploy|import|load|execute_process|run_process|"
            r"submit|approve|reject|commit|save)",
            re.I,
        ),
    ),
    (
        RiskLevel.CONTROLLED_WRITE,
        re.compile(r"(sandbox|draft|stage|checkout|reserve|lock)", re.I),
    ),
    (
        RiskLevel.ANALYSIS,
        re.compile(
            r"(analyz|analys|impact|outlier|forecast|predict|explain|"
            r"compare|diagnos|detect|summar)",
            re.I,
        ),
    ),
    (
        RiskLevel.READ,
        re.compile(
            r"^(get|list|read|fetch|describe|search|find|query|view|show|"
            r"count|status|health|discover|export)",
            re.I,
        ),
    ),
)


@dataclass(frozen=True)
class ToolRiskAssessment:
    tool_name: str
    risk: RiskLevel
    executable: bool
    reason: str


def classify(tool_name: str) -> RiskLevel:
    """Classify a tool from its name alone.

    Note the signature: there is no `description` parameter. The tool's
    own self-description is untrusted and must not influence this.
    """

    if not tool_name or not isinstance(tool_name, str):
        return RiskLevel.UNCLASSIFIED

    for level, pattern in _RULES:
        if pattern.search(tool_name):
            return level

    return RiskLevel.UNCLASSIFIED


def is_executable(risk: RiskLevel) -> bool:
    """Whether this phase permits execution at this risk level."""

    return risk in EXECUTABLE_RISK_LEVELS


def assess(tool_name: str) -> ToolRiskAssessment:
    """Full assessment, with a reason fit to show in the inspector."""

    risk = classify(tool_name)
    executable = is_executable(risk)

    if risk is RiskLevel.UNCLASSIFIED:
        reason = (
            "This tool matched no known risk rule. Unclassified tools are "
            "never executable — a human must classify it explicitly."
        )
    elif executable:
        reason = "Read-only capability permitted in this phase."
    else:
        reason = (
            f"{risk.value} tools are discovered and displayed but blocked "
            "in this phase (BLOCKED_IN_PHASE_1_6)."
        )

    return ToolRiskAssessment(
        tool_name=tool_name,
        risk=risk,
        executable=executable,
        reason=reason,
    )
