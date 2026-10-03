"""What a change to one TM1 object affects, ranked by how badly.

The dependency map says what depends on what. Impact analysis turns that
into a decision a reviewer can make: every object a change reaches, with a
severity and a one-line reason, and a count per severity at the top —
"3 critical, 7 high" is read before anything else.

Severity is a rule, not a judgment, so the same change always gets the same
answer and anyone can check why:

* The kind of dependency decides the base. A cube built on a dimension, a
  chore that runs a process, a rule that reads a cube through DB(): if the
  object is deleted those break outright (critical). If it is only modified
  they usually keep working but may now behave differently (medium or high).
* Distance lowers it. An object reached through another one is one step
  less severe per extra hop: it is affected only if the step between holds.
* A process's own writes count too. Changing or removing a load changes the
  data in the cubes it writes, even though nothing "depends on" the process.

What the map does not hold is listed as not covered rather than implied to
be safe: security, reports and books, other servers, and anything built
from variables at runtime.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException
from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.history import graph_freshness

SEVERITIES = ("critical", "high", "medium", "low")
CHANGE_KINDS = ("modify", "delete")
MAX_DEPTH = 4

# (relationship of the dependent to the changed object) -> (modify, delete)
_BASE: dict[str, tuple[str, str]] = {
    "uses_dimension": ("high", "critical"),
    "references_cube": ("medium", "critical"),
    "calls_process": ("medium", "critical"),
    "runs_process": ("medium", "critical"),
    "view_of_cube": ("low", "high"),
    "subset_of_dimension": ("low", "high"),
    "reads_cube": ("medium", "high"),
    "reads_view": ("medium", "high"),
    "uses_view": ("medium", "high"),
    "uses_subset": ("medium", "high"),
    "references_dimension": ("medium", "high"),
    "updates_cube": ("medium", "high"),
    "updates_dimension": ("medium", "high"),
}
_DEFAULT = ("low", "medium")

_REASON = {
    "uses_dimension": "is built on it",
    "references_cube": "has rules that read it",
    "calls_process": "runs it with ExecuteProcess",
    "runs_process": "runs it on a schedule",
    "view_of_cube": "is a view of it",
    "subset_of_dimension": "is a subset of it",
    "reads_cube": "reads data from it",
    "reads_view": "loads from this view",
    "uses_view": "uses this view",
    "uses_subset": "uses this subset",
    "references_dimension": "looks elements up in it",
    "updates_cube": "writes data into it",
    "updates_dimension": "changes its elements or attributes",
}

NOT_COVERED = [
    "TM1 security: which groups can read or write the affected objects",
    "Reports, Excel / PAW books and websheets built on the affected cubes",
    "Other TM1 servers and external systems that read from or load into this one",
    "References built from variables at runtime (counted at extraction, not drawn)",
]


def _lower(severity: str, steps: int) -> str:
    index = SEVERITIES.index(severity) + max(steps, 0)
    return SEVERITIES[min(index, len(SEVERITIES) - 1)]


def _item(object_type, name, severity, reason, depth, relationship, via=None) -> dict:
    return {
        "object_type": object_type,
        "name": name,
        "severity": severity,
        "reason": reason,
        "depth": depth,
        "relationship_type": relationship,
        "via": via,
    }


async def analyze_impact(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    object_type: str,
    name: str,
    *,
    change_kind: str = "modify",
    rules_change: bool = False,
) -> dict:
    """Everything a change to (object_type, name) affects, ranked.

    `rules_change` is a modification of a cube's rules: the cube's own
    rule-calculated values change, and so does everything that reads them.
    """

    if change_kind not in CHANGE_KINDS:
        raise ValueError(f"change_kind must be one of {CHANGE_KINDS}")

    column = 0 if change_kind == "modify" else 1
    graph = await graph_freshness(db, connection_id)

    try:
        dependents = await dependency_analyzer.find_dependents(
            db, connection_id, organization_id, object_type, name, max_depth=MAX_DEPTH
        )
        written = (
            await dependency_analyzer.find_dependencies(
                db, connection_id, organization_id, object_type, name, max_depth=1
            )
            if object_type == "process"
            else []
        )
    except NotFoundException:
        return {
            "target": {"object_type": object_type, "name": name},
            "change_kind": change_kind,
            "in_graph": False,
            "summary": dict.fromkeys(SEVERITIES, 0),
            "items": [],
            "not_covered": [
                f"{object_type} '{name}' is not in the dependency map, so nothing "
                "it affects is known. Run metadata extraction, then analyse again.",
                *NOT_COVERED,
            ],
            "graph": graph,
        }

    items: list[dict] = []

    if rules_change:
        items.append(_item(
            "cube", name, "high",
            "its rule-calculated values change with the new rules", 0, "rules",
        ))

    # A process changes the data it writes, whatever depends on it.
    for target in written:
        if target["relationship_type"] in ("updates_cube", "updates_dimension"):
            what = "data" if target["relationship_type"] == "updates_cube" else "elements or attributes"
            items.append(_item(
                target["object_type"], target["name"],
                "high" if change_kind == "delete" else "medium",
                (
                    f"its {what} would no longer be maintained by this process"
                    if change_kind == "delete"
                    else f"its {what} are written by this process and will change with it"
                ),
                1, target["relationship_type"],
            ))

    for dependent in dependents:
        relationship = dependent["relationship_type"]
        base = _BASE.get(relationship, _DEFAULT)[column]
        depth = dependent["depth"]
        if rules_change and relationship == "references_cube":
            base = "high"  # its values are computed from the values that change
        severity = _lower(base, depth - 1)
        via = dependent.get("via")
        reason = f"{_REASON.get(relationship, relationship.replace('_', ' '))} " + (
            f"'{name}'" if depth == 1 else f"'{via}', which depends on '{name}'"
        )
        items.append(_item(
            dependent["object_type"], dependent["name"], severity, reason,
            depth, relationship, via,
        ))

    # One entry per object: the most severe way it is affected.
    best: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item["object_type"], item["name"].lower())
        if key not in best or SEVERITIES.index(item["severity"]) < SEVERITIES.index(best[key]["severity"]):
            best[key] = item

    ranked = sorted(
        best.values(),
        key=lambda i: (SEVERITIES.index(i["severity"]), i["depth"], i["object_type"], i["name"].lower()),
    )

    summary = dict.fromkeys(SEVERITIES, 0)
    for item in ranked:
        summary[item["severity"]] += 1

    return {
        "target": {"object_type": object_type, "name": name},
        "change_kind": change_kind,
        "in_graph": True,
        "summary": summary,
        "items": ranked,
        "not_covered": NOT_COVERED,
        "graph": graph,
    }


def needs_acknowledgement(impact: list | None) -> bool:
    """Whether approving a change with this impact must confirm it was read."""

    return any(
        isinstance(entry, dict) and entry.get("severity") in ("critical", "high")
        for entry in impact or []
    )
