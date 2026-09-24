"""Parse TM1 cube rule text into statements.

There is no public grammar for TM1 rules, so this is a pragmatic parser
rather than a complete one. It recovers the structure the analysis in
`analysis.py` needs and nothing more:

* which directives are declared (`SKIPCHECK`, `FEEDSTRINGS`, `UNDEFVALS`)
* where the `FEEDERS;` boundary falls
* for each statement: its target area, its qualifier, and its line number

Statements are split on semicolons that fall outside a comment and outside
a string literal. A rule file that would not compile may parse here - this
is deliberate, because the server's own rule check is authoritative for
syntax and duplicating it badly would produce contradictory errors.

An area is recorded as the list of element names quoted inside its leading
bracket groups: `['Gross Margin']` gives `["Gross Margin"]`. TM1 areas name
elements, not dimensions, so that is the whole of it. Statements whose
target cannot be read as a bracket area (a `DB(...)` feeder target, for
example) are kept with `elements = []` and flagged `resolvable = False`, so
the analysis can lower its own confidence rather than report a finding it
cannot stand behind.
"""

import re
from dataclasses import dataclass, field

DIRECTIVES = ("SKIPCHECK", "FEEDSTRINGS", "UNDEFVALS")
FEEDERS_MARKER = "FEEDERS"

# Leading bracket groups: ['a'] or ['a','b'] or ['a']['b']
_AREA = re.compile(r"^\s*((?:\[[^\]]*\]\s*)+)")
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")
# A qualifier sits between the area and the expression: = N: ... / = S: ...
_QUALIFIER = re.compile(r"^\s*([NSC])\s*:", re.IGNORECASE)


@dataclass
class Statement:
    """One rule statement, with enough position to point a human at it."""

    line_number: int
    text: str
    elements: list[str] = field(default_factory=list)
    qualifier: str | None = None
    expression: str = ""
    is_feeder: bool = False
    target_elements: list[str] = field(default_factory=list)
    resolvable: bool = True


@dataclass
class ParsedRules:
    directives: set[str] = field(default_factory=set)
    calculations: list[Statement] = field(default_factory=list)
    feeders: list[Statement] = field(default_factory=list)
    has_feeders_section: bool = False
    #: Statements found after FEEDERS; that are assignments, not feeders.
    misplaced_calculations: list[Statement] = field(default_factory=list)

    @property
    def skipcheck(self) -> bool:
        return "SKIPCHECK" in self.directives

    @property
    def feedstrings(self) -> bool:
        return "FEEDSTRINGS" in self.directives


def _strip_comments(text: str) -> str:
    """Blank out comments, preserving line structure so numbers stay true."""

    out = []
    for line in text.splitlines():
        in_string = False
        quote = ""
        cut = len(line)
        for i, ch in enumerate(line):
            if in_string:
                if ch == quote:
                    in_string = False
            elif ch in "'\"":
                in_string = True
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def _split_statements(text: str) -> list[tuple[int, str]]:
    """Split on semicolons outside string literals, keeping line numbers."""

    statements: list[tuple[int, str]] = []
    buffer: list[str] = []
    line_number = 1
    start_line = 1
    in_string = False
    quote = ""

    for ch in text:
        if ch == "\n":
            line_number += 1
            if not buffer or not "".join(buffer).strip():
                start_line = line_number

        if in_string:
            if ch == quote:
                in_string = False
            buffer.append(ch)
            continue

        if ch in "'\"":
            in_string = True
            quote = ch
            buffer.append(ch)
            continue

        if ch == ";":
            body = "".join(buffer).strip()
            if body:
                statements.append((start_line, body))
            buffer = []
            start_line = line_number
            continue

        buffer.append(ch)

    trailing = "".join(buffer).strip()
    if trailing:
        # A statement with no terminating semicolon. Kept so the analysis
        # can see it; the server's rule check will reject it separately.
        statements.append((start_line, trailing))

    return statements


def _elements_of(area: str) -> list[str]:
    found = []
    for single, double in _QUOTED.findall(area):
        value = (single or double).strip()
        if value:
            found.append(value)
    return found


def _parse_target(fragment: str) -> tuple[list[str], bool]:
    """Read a feeder's right-hand side. Returns (elements, resolvable)."""

    match = _AREA.match(fragment)
    if not match:
        # DB('Other', !Month) and friends: a real target we cannot resolve
        # statically. Say so rather than treating it as feeding nothing.
        return [], False
    return _elements_of(match.group(1)), True


def parse_rules(text: str | None) -> ParsedRules:
    parsed = ParsedRules()
    if not text or not text.strip():
        return parsed

    body = _strip_comments(text)
    in_feeders = False

    for line_number, raw in _split_statements(body):
        upper = raw.strip().upper()

        if upper in DIRECTIVES:
            parsed.directives.add(upper)
            continue

        if upper == FEEDERS_MARKER:
            parsed.has_feeders_section = True
            in_feeders = True
            continue

        match = _AREA.match(raw)
        area = match.group(1) if match else ""
        remainder = raw[match.end() :] if match else raw

        statement = Statement(
            line_number=line_number,
            text=" ".join(raw.split()),
            elements=_elements_of(area),
            resolvable=bool(match),
        )

        if "=>" in remainder:
            statement.is_feeder = True
            target = remainder.split("=>", 1)[1]
            statement.target_elements, resolved = _parse_target(target)
            statement.resolvable = statement.resolvable and resolved
            parsed.feeders.append(statement)
            continue

        expression = remainder.lstrip()
        if expression.startswith("="):
            expression = expression[1:]

        qualifier = _QUALIFIER.match(expression)
        if qualifier:
            statement.qualifier = qualifier.group(1).upper()
            expression = expression[qualifier.end() :]

        statement.expression = expression.strip()

        if in_feeders:
            # An assignment below FEEDERS; is almost always a statement that
            # was meant to sit above it, and TM1 will not calculate it.
            parsed.misplaced_calculations.append(statement)
        else:
            parsed.calculations.append(statement)

    return parsed
