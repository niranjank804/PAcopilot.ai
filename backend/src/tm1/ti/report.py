"""Render the Company Standards Report from a parsed corpus.

The report is what a TM1 lead would want on the first day of a review: what
this team's processes actually do, which practices are consistent enough to
call standards, and — the part that matters most — which good practices are
*not* consistent. A report that only lists what a team does well is a
compliment, not an audit.
"""

from collections import Counter
from collections.abc import Sequence

from src.tm1.ti.conventions import CodingDNA, infer_conventions
from src.tm1.ti.parser import SECTIONS, ProcessRecord
from src.tm1.ti.patterns import PATTERNS, classify

# Practices worth reporting on even when a corpus does them rarely, because
# their absence is the finding. Measured the same way as any convention; only
# the framing differs.
_HEALTH_CHECKS = (
    ("error_handling", "Validates input and fails deliberately", "uses_error_handling"),
    ("logging", "Writes an execution log", "uses_logging"),
)


def _percent(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.0f}%" if whole else "n/a"


def build_report(records: Sequence[ProcessRecord]) -> dict:
    """Compute the report as structured data; rendering is separate."""

    total = len(records)
    dna: CodingDNA = infer_conventions(records)

    pattern_counts: Counter = Counter()
    for record in records:
        for match in classify(record):
            pattern_counts[match.key] += 1

    datasources = Counter(r.datasource_type for r in records)

    functions: Counter = Counter()
    for record in records:
        for name, count in record.functions_used.items():
            functions[name] += count

    health = []
    for key, label, attribute in _HEALTH_CHECKS:
        followed = sum(1 for r in records if getattr(r, attribute, False))
        health.append(
            {
                "key": key,
                "practice": label,
                "followed": followed,
                "total": total,
                "share": _percent(followed, total),
            }
        )

    creates_temporary = [
        r for r in records if any(o.access == "create" for o in r.objects)
    ]
    cleans_up = [r for r in creates_temporary if r.has_cleanup]
    health.append(
        {
            "key": "cleanup",
            # Deliberately narrower than the `cleanup` pattern, which counts a
            # destroy call anywhere. Cleanup that only runs in the Data tab is
            # skipped when a process errors, so the Epilog is the part that
            # actually protects the server.
            "practice": "Destroys the objects it created, in the Epilog",
            "followed": len(cleans_up),
            "total": len(creates_temporary),
            "share": _percent(len(cleans_up), len(creates_temporary)),
        }
    )

    return {
        "process_count": total,
        "conventions": [c.as_dict() for c in dna.conventions],
        "established": [c.as_dict() for c in dna.enforced()],
        "naming": dna.naming,
        "section_usage": {
            section: _percent(
                sum(1 for r in records if r.line_counts.get(section, 0) > 3), total
            )
            for section in SECTIONS
        },
        "datasources": dict(datasources.most_common()),
        "patterns": [
            {
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "count": pattern_counts.get(p.key, 0),
            }
            for p in PATTERNS
            if pattern_counts.get(p.key, 0)
        ],
        "unclassified": sum(1 for r in records if not classify(r)),
        "top_functions": functions.most_common(20),
        "health": health,
        "credentials_in_exports": sum(
            1 for r in records if r.has_stored_credentials
        ),
    }


def render_markdown(report: dict) -> str:
    """Render the report for a human reader."""

    total = report["process_count"]
    lines: list[str] = [
        "# Company TM1 Standards Report",
        "",
        f"Measured from {total} exported TurboIntegrator processes. Every figure "
        "below is counted from the source, not estimated.",
        "",
        "## Established standards",
        "",
    ]

    if report["established"]:
        lines.append("These practices are consistent enough to hold new code to.")
        lines.append("")
        lines.append("| Convention | Followed by | Confidence |")
        lines.append("| --- | --- | --- |")
        for convention in report["established"]:
            lines.append(
                f"| {convention['statement']} "
                f"| {convention['support']} of {convention['sample']} "
                f"| {convention['confidence']:.2f} |"
            )
    else:
        lines.append(
            "No practice was consistent enough across this corpus to call a "
            "standard. That is itself the finding."
        )

    lines += ["", "## Practices that are not yet standards", ""]
    lines.append(
        "Each of these is a widely accepted TM1 practice. The share shows how "
        "often this codebase actually follows it."
    )
    lines += ["", "| Practice | Followed by | Share |", "| --- | --- | --- |"]
    for check in report["health"]:
        lines.append(
            f"| {check['practice']} | {check['followed']} of {check['total']} "
            f"| {check['share']} |"
        )

    lines += [
        "",
        "## What these processes do",
        "",
        "A process can implement several patterns at once, so these counts "
        "overlap and do not sum to the corpus size.",
        "",
        "| Pattern | Processes |",
        "| --- | --- |",
    ]
    for pattern in report["patterns"]:
        lines.append(f"| {pattern['name']} | {pattern['count']} |")

    if report["unclassified"]:
        lines += [
            "",
            f"{report['unclassified']} processes matched no standard pattern. "
            "These are typically single-purpose administrative utilities.",
        ]

    lines += ["", "## Data sources", "", "| Type | Processes |", "| --- | --- |"]
    for name, count in report["datasources"].items():
        lines.append(f"| {name} | {count} |")

    lines += ["", "## Section usage", "", "| Section | Processes using it |", "| --- | --- |"]
    for section, share in report["section_usage"].items():
        lines.append(f"| {section.title()} | {share} |")

    lines += ["", "## Most used TM1 functions", "", "| Function | Calls |", "| --- | --- |"]
    for name, count in report["top_functions"][:15]:
        lines.append(f"| {name} | {count} |")

    if report["credentials_in_exports"]:
        lines += [
            "",
            "## Security note",
            "",
            f"{report['credentials_in_exports']} of {total} exports carry a stored "
            "datasource username or password. These were flagged and excluded "
            "from all parsed output, but the export files themselves should be "
            "treated as secret material and not circulated.",
        ]

    return "\n".join(lines) + "\n"
