"""What a TM1 process error log is saying, and whether it is still true.

TM1 writes the same few kinds of failure in recognisable words: an element
a lookup or a cell write could not find, an object that does not exist, a
value that would not convert, a data source that would not open. Naming the
kind turns "here is a log" into "here is what went wrong", and each kind
says what to check and what a fix usually looks like.

Two levels of certainty, kept apart on purpose:

* **The category is a reading of TM1's words** — a pattern, so INFERRED,
  with the line it was read from as evidence.
* **A check against the live model is VERIFIED** — "element 2027 does not
  exist in Year now" is a fact read from TM1 in this call, and it is what
  separates "the data had a new year" from "the code has a typo".

Nothing here guesses beyond the words in the log. A message no pattern
recognises is reported as unclassified, not forced into a category.
"""

import re
import uuid
from dataclasses import dataclass, field

from TM1py import TM1Service

from src.tm1.services import structure_service

# Lines of a log scanned for failures without a code line (a data source
# that would not open has none).
MAX_SCANNED_LINES = 40
# Live checks per diagnosis: each is one TM1 request.
MAX_CHECKS = 10

_Q = r'"?([^"\n]+?)"?'


@dataclass
class _Pattern:
    category: str
    regex: re.Pattern
    meaning: str
    fix: str


_PATTERNS: list[_Pattern] = [
    _Pattern(
        "element_not_found",
        re.compile(
            r'invalid key:\s*dimension name:\s*"(?P<dimension>[^"]+)",\s*element name \(key\):\s*"(?P<element>[^"]+)"',
            re.IGNORECASE,
        ),
        "A lookup or cell write named an element that is not in the dimension.",
        "Add the missing element to the dimension (usually in the metadata step "
        "of the load that builds it), or skip or map records whose value has no "
        "element (DIMIX check before the write).",
    ),
    _Pattern(
        "element_not_found",
        re.compile(
            rf"element\s+{_Q}\s+(?:not found|does not exist)\s+in\s+dimension\s+{_Q}(?=[\s.,;]|$)",
            re.IGNORECASE,
        ),
        "A lookup or cell write named an element that is not in the dimension.",
        "Add the missing element to the dimension (usually in the metadata step "
        "of the load that builds it), or skip or map records whose value has no "
        "element (DIMIX check before the write).",
    ),
    _Pattern(
        "element_not_found",
        re.compile(r'"(?P<element>[^"]+)"\s*:\s*(?:member|element)\s+not\s+found', re.IGNORECASE),
        "A value in the data did not match any element.",
        "Find which dimension the value belongs to (the code line shows the "
        "write), then add the element or skip records without one.",
    ),
    _Pattern(
        "object_not_found",
        re.compile(
            r"\b(?P<kind>cube|dimension|process|subset|view)\s+\"(?P<name>[^\"]+)\"\s+"
            r"(?:not found|does not exist|doesn't exist|was not found)",
            re.IGNORECASE,
        ),
        "The process names a cube, dimension, process, view or subset that does not exist.",
        "Correct the name in the code, or create the object first (a view or "
        "subset the process builds itself must be created before it is used).",
    ),
    _Pattern(
        "conversion",
        re.compile(
            r'cannot convert field number\s+(?P<field>\d+),\s*value\s+"(?P<value>[^"]*)"',
            re.IGNORECASE,
        ),
        "A source field declared numeric held text (or an empty or malformed number).",
        "Check the variable's type on the Variables tab against the source, or "
        "convert explicitly with NUMBR and handle blanks before the write.",
    ),
    _Pattern(
        "data_source",
        re.compile(
            r"(?:unable to open|error opening|cannot open|could not open)\b.{0,60}"
            r"|data\s*source\b.{0,60}(?:not found|error|failed)"
            r"|\bodbc\b.{0,80}(?:error|failed|login)",
            re.IGNORECASE,
        ),
        "The data source could not be opened: a file path, an ODBC connection or a view.",
        "Check the file exists at that path on the TM1 server (paths are the "
        "server's, not your PC's), the ODBC DSN and credentials, or the view.",
    ),
    _Pattern(
        "consolidated_write",
        re.compile(
            r"consolidat\w*\s+(?:element|cell|member)|"
            r"(?:cannot|unable to)\s+(?:write|put|update|input)\b.{0,40}consolidat",
            re.IGNORECASE,
        ),
        "A write targeted a consolidated cell, which holds the sum of its children.",
        "Write to leaf elements only (or use CellPutProportionalSpread for a "
        "deliberate spread); check which element in the write is a consolidation.",
    ),
    _Pattern(
        "rule_derived",
        re.compile(r"rule[-\s]?derived|calculated by (?:a )?rule", re.IGNORECASE),
        "A write targeted a cell a rule calculates, which cannot hold input.",
        "Write to the cells the rule reads from, or change the rule's scope so "
        "it does not cover this cell.",
    ),
    _Pattern(
        "security_or_lock",
        re.compile(
            r"not authori[sz]ed|access denied|insufficient (?:access|rights|privilege)"
            r"|\block(?:ed)?\s+(?:by|conflict)|object is locked",
            re.IGNORECASE,
        ),
        "TM1 security, or another session's lock, stopped the step.",
        "Check the process's own security setting and the group rights on the "
        "object; for a lock, the conflicting session (server state / threads).",
    ),
    _Pattern(
        "mdx",
        re.compile(r"\bmdx\b.{0,60}(?:syntax|error|invalid)|syntax error.{0,40}\bmdx\b", re.IGNORECASE),
        "An MDX expression (a subset or view built by MDX) did not parse or resolve.",
        "Check the expression's member names and brackets; run the MDX on its "
        "own to see the exact error.",
    ),
    _Pattern(
        "process_quit",
        re.compile(r"\bprocessquit\b|process\s+quit|execution\s+was\s+aborted", re.IGNORECASE),
        "The process stopped itself (ProcessQuit) or was aborted.",
        "Look for the condition before the ProcessQuit in the code; it usually "
        "guards a parameter or a precondition the run did not meet.",
    ),
]


@dataclass
class Finding:
    category: str
    message: str
    meaning: str
    fix_direction: str
    entities: dict = field(default_factory=dict)
    section: str | None = None
    line_number: int | None = None
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "message": self.message,
            "section": self.section,
            "line_number": self.line_number,
            "entities": self.entities,
            "meaning": self.meaning,
            "fix_direction": self.fix_direction,
            "checks": self.checks,
        }


def classify(message: str) -> Finding | None:
    """The kind of failure a TM1 error message describes, or None."""

    for pattern in _PATTERNS:
        match = pattern.regex.search(message or "")

        if not match:
            continue

        entities = {k: v.strip() for k, v in match.groupdict().items() if v}

        # The element/dimension pattern without named groups captures
        # positionally: element first, dimension second.
        if pattern.category == "element_not_found" and not entities and match.groups():
            entities = {"element": match.group(1).strip(), "dimension": match.group(2).strip()}
        if "kind" in entities:
            entities["kind"] = entities["kind"].lower()

        return Finding(
            category=pattern.category,
            message=message.strip()[:500],
            meaning=pattern.meaning,
            fix_direction=pattern.fix,
            entities=entities,
        )

    return None


def findings_from_log(locations: list[dict], log_text: str) -> tuple[list[Finding], list[str]]:
    """Classify every located error, then any other failure line in the
    log (a data source error has no code line). Returns the findings and
    the located messages no pattern recognised."""

    findings: list[Finding] = []
    unclassified: list[str] = []
    seen: set[tuple[str, str]] = set()

    for location in locations:
        finding = classify(location.get("message", ""))

        if finding is None:
            unclassified.append(location.get("message", "")[:300])
            continue

        finding.section = location.get("section")
        finding.line_number = location.get("line_number")
        key = (finding.category, repr(sorted(finding.entities.items())))

        if key not in seen:
            seen.add(key)
            findings.append(finding)

    located = {(loc.get("message") or "").strip() for loc in locations}

    for line in (log_text or "").splitlines()[:MAX_SCANNED_LINES]:
        if not line.strip() or any(m and m in line for m in located):
            continue

        finding = classify(line)

        if finding is None:
            continue

        key = (finding.category, repr(sorted(finding.entities.items())))

        if key not in seen:
            seen.add(key)
            findings.append(finding)

    return findings, unclassified


async def verify(client: TM1Service, connection_id: uuid.UUID, findings: list[Finding]) -> None:
    """Check each finding's claim against the model as it is now.

    Only claims that can be settled by one existence check are checked;
    the rest are left to the reader, and say so. A check that cannot be
    made (the server refused, the dimension is unknown) is reported as
    such, never as a pass or a fail.
    """

    budget = MAX_CHECKS

    async def exists(kind: str, name: str, dimension: str | None = None) -> bool | None:
        nonlocal budget
        if budget <= 0:
            return None
        budget -= 1
        try:
            return await structure_service.object_exists(
                client, connection_id, kind, name, dimension_name=dimension
            )
        except Exception:  # noqa: BLE001 - a check that fails is reported as not made
            return None

    for finding in findings:
        entities = finding.entities

        if finding.category == "element_not_found":
            dimension, element = entities.get("dimension"), entities.get("element")

            if not element:
                continue
            if not dimension:
                finding.checks.append({
                    "check": f"Is '{element}' an element?",
                    "result": "not checked: the log does not name the dimension; the code line shows which write it was",
                })
                continue

            dimension_exists = await exists("dimension", dimension)
            if dimension_exists is False:
                finding.checks.append({
                    "check": f"Does dimension '{dimension}' exist?",
                    "result": "no — the dimension itself does not exist now",
                })
                continue

            present = await exists("element", element, dimension)
            finding.checks.append({
                "check": f"Is '{element}' in dimension '{dimension}' now?",
                "result": (
                    "no — it is still missing, so a re-run fails the same way until it is added or skipped"
                    if present is False
                    else "yes — it exists now (added after the run, or the run used a different value)"
                    if present
                    else "could not be checked"
                ),
            })

        elif finding.category == "object_not_found":
            kind, name = entities.get("kind"), entities.get("name")

            if kind not in ("cube", "dimension", "process") or not name:
                continue

            present = await exists(kind, name)
            finding.checks.append({
                "check": f"Does {kind} '{name}' exist now?",
                "result": (
                    "no — still missing"
                    if present is False
                    else "yes — it exists now"
                    if present
                    else "could not be checked"
                ),
            })
