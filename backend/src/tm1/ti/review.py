"""Deterministic review of one TurboIntegrator process.

Every finding carries the same six things — severity, object, evidence,
reason, recommendation, confidence — so a reviewer can check each one
against the code rather than trust it. Nothing here is inferred by a
model: the findings come from the TI parser, `deployment/ti_analysis.py`
and the function reference, and a function is only ever named if the
reference knows it (a unit test asserts that for every name below).

What this deliberately does not do: judge business logic, or say a
process is "correct". It says what the code demonstrably does and where
that is risky.
"""

import re
from dataclasses import asdict, dataclass

from src.tm1.deployment import ti_analysis
from src.tm1.functions import validate_process as validate_functions
from src.tm1.ti.parser import SECTIONS, ProcessRecord


@dataclass
class ReviewFinding:
    severity: str  # error | warning | info
    category: str  # syntax | compatibility | danger | complexity | maintainability | naming | documentation
    object: str
    evidence: str
    reason: str
    recommendation: str
    confidence: str  # high | medium | low
    section: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


#: TI functions whose effect is destructive, wide or outside TM1, with
#: why each matters. Only names the function reference knows are listed.
DANGEROUS_FUNCTIONS: dict[str, tuple[str, str]] = {
    "CUBECLEARDATA": ("warning", "Clears every cell in a cube. A wrong cube name empties the wrong model."),
    "CUBEDESTROY": ("warning", "Deletes a cube and its data."),
    "DIMENSIONDESTROY": ("warning", "Deletes a dimension; every cube using it breaks."),
    "HIERARCHYDESTROY": ("warning", "Deletes a hierarchy."),
    "DIMENSIONDELETEALLELEMENTS": ("warning", "Removes every element; cube data at leaf level is lost unless the elements are rebuilt in the same transaction."),
    "HIERARCHYDELETEALLELEMENTS": ("warning", "Removes every element of a hierarchy."),
    "DIMENSIONELEMENTDELETE": ("info", "Deleting an element deletes its data in every cube."),
    "HIERARCHYELEMENTDELETE": ("info", "Deleting an element deletes its data in every cube."),
    "DELETEALLPERSISTENTFEEDERS": ("warning", "Drops persistent feeders; the next load re-evaluates feeders for the whole model."),
    "CUBEUNLOAD": ("info", "Unloads a cube from memory; the next read reloads it from disk."),
    "SAVEDATAALL": ("warning", "Saves every cube and takes a server-wide lock while it does."),
    "SERVERSHUTDOWN": ("error", "Shuts the TM1 server down."),
    "SECURITYREFRESH": ("info", "Rebuilds security and locks the server while it runs."),
    "DELETECLIENT": ("warning", "Deletes a TM1 user."),
    "DELETEGROUP": ("warning", "Deletes a security group."),
    "EXECUTECOMMAND": ("warning", "Runs an operating-system command on the TM1 server."),
    "ASCIIDELETE": ("info", "Deletes a file on the TM1 server."),
    "CUBEDATARESERVATIONRELEASEALL": ("info", "Releases every data reservation on a cube, including other users'."),
}

# Complexity thresholds. Chosen to flag the outliers a reviewer should
# look at first, not to grade style.
MAX_STATEMENTS = 400
MAX_NESTING = 5
MAX_EXECUTE_PROCESS = 10

_IF_OPEN = re.compile(r"^\s*(IF|WHILE)\s*\(", re.IGNORECASE)
_BLOCK_CLOSE = re.compile(r"^\s*(ENDIF|END)\s*;", re.IGNORECASE)
_WHILE = re.compile(r"(?<![A-Za-z0-9_])WHILE\s*\(", re.IGNORECASE)
_NOISE = re.compile(r"'(?:[^']|'')*'|#[^\n]*")
_COMMENTED_CODE = re.compile(r"^\s*#\s*[A-Za-z][A-Za-z0-9_]*\s*\(.*\)\s*;\s*$")


def _strip(code: str) -> str:
    return _NOISE.sub(lambda m: " " * len(m.group(0)), code)


def complexity(record: ProcessRecord) -> dict:
    """Plain counts a reviewer can check by eye."""

    depth = 0
    deepest = 0
    statements = 0
    loops = 0

    for section in SECTIONS:
        code = _strip(getattr(record, section))
        statements += code.count(";")
        loops += len(_WHILE.findall(code))

        for line in code.splitlines():
            if _IF_OPEN.match(line):
                depth += 1
                deepest = max(deepest, depth)
            elif _BLOCK_CLOSE.match(line):
                depth = max(depth - 1, 0)

    return {
        "lines": sum(record.line_counts.get(s, 0) for s in SECTIONS),
        "statements": statements,
        "loops": loops,
        "max_nesting": deepest,
        "processes_called": len(record.processes_called),
        "cubes_written": sorted(record.cubes_written),
        "cubes_read": sorted(record.cubes_read),
    }


def _first_line(record: ProcessRecord, function: str) -> tuple[str | None, int | None, str]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){function}\s*[(;]", re.IGNORECASE)

    for section in SECTIONS:
        for number, line in enumerate(getattr(record, section).splitlines(), start=1):
            stripped = _strip(line)
            if pattern.search(stripped):
                return section, number, line.strip()[:200]

    return None, None, function


def review(
    record: ProcessRecord,
    *,
    version: str | None = None,
) -> tuple[list[ReviewFinding], dict]:
    """Findings and complexity metrics for one process."""

    target = f"process:{record.name}"
    findings: list[ReviewFinding] = []
    sections = {s: getattr(record, s) for s in SECTIONS}

    # Syntax-level problems the static analyser proves: undefined names,
    # case mismatches. High confidence — each names the line.
    for message in ti_analysis.analyze(
        {
            **sections,
            # Lowercase keys: ti_analysis reads "name". Passing "Name" makes
            # every parameter look undefined.
            "parameters": [{"name": p.get("name", "")} for p in record.parameters],
            "variables": [{"name": v.get("name", "")} for v in record.variables],
        },
        datasource_type=record.datasource_type,
    ):
        findings.append(
            ReviewFinding(
                severity="error",
                category="syntax",
                object=target,
                evidence=message,
                reason="The static analyser found a name used before it is defined, or a case mismatch TM1 would reject or misread.",
                recommendation="Define the variable before use, or correct the spelling, then compile.",
                confidence="high",
            )
        )

    # Function usage against the reference: wrong context, or missing on
    # the target version (v12 readiness when version="v12").
    for issue in validate_functions(sections, version=version):
        findings.append(
            ReviewFinding(
                severity="error",
                category="compatibility",
                object=target,
                evidence=f"{issue['function']} (line {issue['line']})",
                reason=issue["message"],
                recommendation=(
                    "Replace it with a function supported on the target version."
                    if issue["kind"] == "version"
                    else "Use the TI equivalent of this function."
                ),
                confidence="high",
                section=issue.get("section"),
                line=issue.get("line"),
            )
        )

    for function in sorted(record.functions_used):
        entry = DANGEROUS_FUNCTIONS.get(function.upper())
        if entry is None:
            continue
        severity, reason = entry
        section, line, evidence = _first_line(record, function)
        findings.append(
            ReviewFinding(
                severity=severity,
                category="danger",
                object=target,
                evidence=evidence,
                reason=reason,
                recommendation="Confirm the target is guarded (parameter checks, an explicit environment test) and that the call is intended on every run.",
                confidence="high",
                section=section,
                line=line,
            )
        )

    metrics = complexity(record)

    if metrics["statements"] > MAX_STATEMENTS:
        findings.append(
            ReviewFinding(
                severity="info",
                category="complexity",
                object=target,
                evidence=f"{metrics['statements']} statements",
                reason=f"More than {MAX_STATEMENTS} statements in one process is hard to review and to test.",
                recommendation="Split it into called sub-processes with one responsibility each.",
                confidence="medium",
            )
        )

    if metrics["max_nesting"] > MAX_NESTING:
        findings.append(
            ReviewFinding(
                severity="info",
                category="complexity",
                object=target,
                evidence=f"IF/WHILE nesting depth {metrics['max_nesting']}",
                reason="Deep nesting hides which branch runs for which record.",
                recommendation="Return early with ItemSkip / ProcessBreak, or move the inner logic into a sub-process.",
                confidence="medium",
            )
        )

    if metrics["processes_called"] > MAX_EXECUTE_PROCESS:
        findings.append(
            ReviewFinding(
                severity="info",
                category="complexity",
                object=target,
                evidence=f"calls {metrics['processes_called']} processes",
                reason="A long ExecuteProcess chain is an orchestration process; a failure in one step is easy to miss.",
                recommendation="Check each call's return value (ProcessExitNormal) before continuing.",
                confidence="medium",
            )
        )

    writes = bool(record.cubes_written)

    if writes and not record.uses_error_handling:
        findings.append(
            ReviewFinding(
                severity="warning",
                category="maintainability",
                object=target,
                evidence=f"writes to {', '.join(sorted(record.cubes_written))}; no ProcessError / ProcessQuit / ItemReject",
                reason="A process that writes data and never fails deliberately runs on bad input instead of stopping.",
                recommendation="Validate parameters in the Prolog and call ProcessError or ProcessQuit when they are wrong.",
                confidence="high",
            )
        )

    leaked = [
        name
        for name in record.temporary_objects
        if not record.has_cleanup and not record.uses_temporary_objects
    ]

    if leaked:
        findings.append(
            ReviewFinding(
                severity="info",
                category="maintainability",
                object=target,
                evidence=", ".join(leaked[:10]),
                reason="Views or subsets that look temporary are created but not destroyed in the Epilog, and are not created with the Temporary flag.",
                recommendation="Create them with the Temporary flag, or destroy them in the Epilog.",
                confidence="medium",
            )
        )

    commented = sum(
        1
        for section in SECTIONS
        for line in getattr(record, section).splitlines()
        if _COMMENTED_CODE.match(line)
    )

    if commented >= 10:
        findings.append(
            ReviewFinding(
                severity="info",
                category="maintainability",
                object=target,
                evidence=f"{commented} commented-out statements",
                reason="Commented-out code is history that belongs in source control.",
                recommendation="Remove it; the previous version is in the change history.",
                confidence="medium",
            )
        )

    if record.line_counts.get("prolog", 0) > 3 and not record.header_comment:
        findings.append(
            ReviewFinding(
                severity="info",
                category="documentation",
                object=target,
                evidence="no comment lines in the process",
                reason="Nothing in the code says what the process is for or who owns it.",
                recommendation="Open the Prolog with a header block: purpose, parameters, author, change history.",
                confidence="high",
            )
        )

    undocumented = [p["name"] for p in record.parameters if p.get("name") and not (p.get("prompt") or "").strip()]

    if undocumented:
        findings.append(
            ReviewFinding(
                severity="info",
                category="documentation",
                object=target,
                evidence=", ".join(undocumented[:10]),
                reason="Parameters with no prompt tell the person running the process nothing about the expected value.",
                recommendation="Give each parameter a prompt stating its format and allowed values.",
                confidence="high",
            )
        )

    prefixes = {re.match(r"[a-z]*", p["name"]).group(0) for p in record.parameters if p.get("name")}

    if len(prefixes) > 1 and len(record.parameters) >= 3:
        findings.append(
            ReviewFinding(
                severity="info",
                category="naming",
                object=target,
                evidence=", ".join(p["name"] for p in record.parameters[:8]),
                reason="Parameters in the same process use different prefixes.",
                recommendation="Use one prefix for every parameter (compare get_coding_standards for the organization's convention).",
                confidence="medium",
            )
        )

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), f.category))

    return findings, metrics
