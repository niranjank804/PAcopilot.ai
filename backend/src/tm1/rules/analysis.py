"""Static analysis of TM1 cube rules and feeders.

This is the check a TM1 developer runs in their head and usually too late:
under `SKIPCHECK`, a calculated cell that nothing feeds is skipped during
consolidation, so every total above it reads zero while every leaf reads
correctly. The rule is right, the number is wrong, and nothing errors.

Findings carry a severity:

* ``critical`` - consolidated values are wrong right now
* ``warning``  - probably a defect, or dead code
* ``info``     - worth knowing, not necessarily wrong

The false-positive stance matches `deployment/ti_analysis.py`: a finding a
developer has to dismiss is worse than a finding we never made. So a
calculation counts as fed when its area shares *any* element with *any*
feeder target, and when a rule file contains feeder targets we cannot
resolve statically (`DB(...)`, for example) the unfed check is reported as
partial rather than asserted.
"""

from dataclasses import asdict, dataclass

from src.tm1.rules.parser import ParsedRules, Statement, parse_rules


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    line_number: int | None = None
    statement: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _fed_elements(parsed: ParsedRules) -> set[str]:
    fed: set[str] = set()
    for feeder in parsed.feeders:
        fed.update(feeder.target_elements)
    return fed


def _has_unresolvable_feeder(parsed: ParsedRules) -> bool:
    return any(not feeder.resolvable for feeder in parsed.feeders)


def _is_calculation(statement: Statement) -> bool:
    """A statement that produces a value, as opposed to a bare area."""

    return bool(statement.expression)


def _check_skipcheck_without_feeders(parsed: ParsedRules) -> list[Finding]:
    if not parsed.skipcheck or parsed.has_feeders_section:
        return []
    if not any(_is_calculation(c) for c in parsed.calculations):
        return []

    return [
        Finding(
            severity="critical",
            code="skipcheck_without_feeders",
            message=(
                "SKIPCHECK is declared but the rule has no FEEDERS section. "
                "Every calculated cell is unfed, so consolidated values above "
                "leaf level will read zero while leaf values look correct."
            ),
        )
    ]


def _check_feeders_without_skipcheck(parsed: ParsedRules) -> list[Finding]:
    if parsed.skipcheck or not parsed.has_feeders_section:
        return []
    if not parsed.feeders:
        return []

    return [
        Finding(
            severity="warning",
            code="feeders_without_skipcheck",
            message=(
                "A FEEDERS section exists but SKIPCHECK is not declared. "
                "Without SKIPCHECK the feeders have no effect and the engine "
                "evaluates every cell, which is usually slower than intended."
            ),
        )
    ]


def _check_unfed_calculations(parsed: ParsedRules) -> list[Finding]:
    """The finding that matters: a calculated area nothing feeds."""

    if not parsed.skipcheck or not parsed.has_feeders_section:
        return []  # covered by the two checks above

    fed = _fed_elements(parsed)
    partial = _has_unresolvable_feeder(parsed)
    findings = []

    for statement in parsed.calculations:
        if not _is_calculation(statement) or not statement.elements:
            continue

        # String rules are only skipped when FEEDSTRINGS is on; a string
        # rule without it is handled by its own check.
        if statement.qualifier == "S" and not parsed.feedstrings:
            continue

        if fed.intersection(statement.elements):
            continue

        findings.append(
            Finding(
                severity="warning" if partial else "critical",
                code="unfed_calculation",
                message=(
                    f"No feeder targets {statement.elements}. Under SKIPCHECK "
                    "this cell is skipped when consolidating, so totals above "
                    "it will read zero."
                    + (
                        " Some feeder targets in this rule could not be "
                        "resolved statically, so confirm before acting."
                        if partial
                        else ""
                    )
                ),
                line_number=statement.line_number,
                statement=statement.text,
            )
        )

    return findings


def _check_misplaced_calculations(parsed: ParsedRules) -> list[Finding]:
    return [
        Finding(
            severity="critical",
            code="calculation_below_feeders",
            message=(
                "This assignment sits below FEEDERS; so TM1 never evaluates "
                "it. Move it above the FEEDERS marker."
            ),
            line_number=statement.line_number,
            statement=statement.text,
        )
        for statement in parsed.misplaced_calculations
    ]


def _check_string_rules_without_feedstrings(parsed: ParsedRules) -> list[Finding]:
    if parsed.feedstrings or not parsed.skipcheck:
        return []

    string_rules = [
        s for s in parsed.calculations if s.qualifier == "S" and _is_calculation(s)
    ]
    if not string_rules:
        return []

    return [
        Finding(
            severity="info",
            code="string_rules_without_feedstrings",
            message=(
                "The rule calculates string values under SKIPCHECK but does "
                "not declare FEEDSTRINGS. String cells will not be fed."
            ),
            line_number=string_rules[0].line_number,
            statement=string_rules[0].text,
        )
    ]


def _check_shadowed_areas(parsed: ParsedRules) -> list[Finding]:
    """TM1 applies the first matching statement; later twins are dead."""

    seen: dict[tuple, Statement] = {}
    findings = []

    for statement in parsed.calculations:
        if not _is_calculation(statement) or not statement.elements:
            continue

        key = (tuple(sorted(statement.elements)), statement.qualifier)
        first = seen.get(key)

        if first is None:
            seen[key] = statement
            continue

        findings.append(
            Finding(
                severity="warning",
                code="shadowed_area",
                message=(
                    f"Area {statement.elements} is already calculated at line "
                    f"{first.line_number}. TM1 applies the first match, so "
                    "this statement never runs."
                ),
                line_number=statement.line_number,
                statement=statement.text,
            )
        )

    return findings


def _check_feeders_to_uncalculated(parsed: ParsedRules) -> list[Finding]:
    if not parsed.feeders:
        return []

    calculated: set[str] = set()
    for statement in parsed.calculations:
        if _is_calculation(statement):
            calculated.update(statement.elements)

    findings = []
    for feeder in parsed.feeders:
        if not feeder.resolvable or not feeder.target_elements:
            continue
        if calculated.intersection(feeder.target_elements):
            continue

        findings.append(
            Finding(
                severity="info",
                code="feeder_to_uncalculated_area",
                message=(
                    f"Feeder targets {feeder.target_elements}, which no rule "
                    "in this cube calculates. This is correct when feeding "
                    "another cube, and wasted work otherwise."
                ),
                line_number=feeder.line_number,
                statement=feeder.text,
            )
        )

    return findings


_CHECKS = (
    _check_skipcheck_without_feeders,
    _check_feeders_without_skipcheck,
    _check_unfed_calculations,
    _check_misplaced_calculations,
    _check_string_rules_without_feedstrings,
    _check_shadowed_areas,
    _check_feeders_to_uncalculated,
)

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def analyze_rules(text: str | None) -> dict:
    """Analyse rule text and return findings plus a short summary."""

    parsed = parse_rules(text)

    findings: list[Finding] = []
    for check in _CHECKS:
        findings.extend(check(parsed))

    findings.sort(
        key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.line_number or 0)
    )

    counts = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    return {
        "summary": {
            "skipcheck": parsed.skipcheck,
            "feedstrings": parsed.feedstrings,
            "has_feeders_section": parsed.has_feeders_section,
            "calculation_count": sum(
                1 for c in parsed.calculations if _is_calculation(c)
            ),
            "feeder_count": len(parsed.feeders),
            "analysis_is_partial": _has_unresolvable_feeder(parsed),
            **counts,
        },
        "findings": [f.to_dict() for f in findings],
    }


def trace_cell(text: str | None, elements: list[str]) -> dict:
    """Which rule statement calculates this intersection, and is it fed?

    `elements` is the element tuple of the cell, in any order. A statement
    applies when every element named in its area appears in the tuple, which
    is how TM1 itself narrows an area.
    """

    parsed = parse_rules(text)
    wanted = {e.strip().lower() for e in elements if e and e.strip()}

    applicable = [
        statement
        for statement in parsed.calculations
        if _is_calculation(statement)
        and statement.elements
        and {e.lower() for e in statement.elements}.issubset(wanted)
    ]

    if not applicable:
        return {
            "elements": elements,
            "calculated": False,
            "message": (
                "No rule statement in this cube applies to that intersection. "
                "The value is stored data or a plain consolidation."
            ),
        }

    # TM1 applies the first matching statement in file order.
    winner = applicable[0]
    fed = bool(_fed_elements(parsed).intersection(winner.elements))

    return {
        "elements": elements,
        "calculated": True,
        "applied_statement": {
            "line_number": winner.line_number,
            "qualifier": winner.qualifier,
            "text": winner.text,
            "expression": winner.expression,
        },
        "also_matched": [
            {"line_number": s.line_number, "text": s.text} for s in applicable[1:]
        ],
        "skipcheck": parsed.skipcheck,
        "is_fed": fed,
        "warning": (
            "SKIPCHECK is on and nothing feeds this area, so consolidations "
            "above it will read zero."
            if parsed.skipcheck and not fed
            else None
        ),
    }
