"""Heuristic extraction of cube references from TM1 rule and TI code.

These are regex/scan heuristics, not a full rule/TI parser: only literal
quoted cube names are detected, and dynamically-built names (variables,
Expand) are ignored.
"""

import re

_RULE_DB_PATTERN = re.compile(r"DB\s*\(\s*'([^']+)'", re.IGNORECASE)

_TI_WRITE_PATTERN = re.compile(
    r"(?:CellPutN|CellPutS|CellIncrementN)\s*\(", re.IGNORECASE
)

_QUOTED_LITERAL_PATTERN = re.compile(r"^'([^']+)'$")


def extract_rule_cube_references(rule_text: str) -> set[str]:
    if not rule_text:
        return set()

    return set(_RULE_DB_PATTERN.findall(rule_text))


def _split_top_level_arguments(code: str, start: int) -> list[str]:
    """Split the argument list of the call whose opening paren is at `start`
    into top-level arguments, respecting nested parens and quoted strings."""

    arguments: list[str] = []
    current: list[str] = []
    depth = 1
    in_quote = False
    position = start + 1

    while position < len(code) and depth > 0:
        char = code[position]

        if in_quote:
            current.append(char)
            if char == "'":
                in_quote = False
        elif char == "'":
            current.append(char)
            in_quote = True
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            if depth > 0:
                current.append(char)
        elif char == "," and depth == 1:
            arguments.append("".join(current))
            current = []
        else:
            current.append(char)

        position += 1

    if current or arguments:
        arguments.append("".join(current))

    return arguments


def extract_ti_cube_writes(code: str) -> set[str]:
    if not code:
        return set()

    cubes: set[str] = set()

    for match in _TI_WRITE_PATTERN.finditer(code):
        arguments = _split_top_level_arguments(code, match.end() - 1)

        if len(arguments) < 2:
            continue

        literal = _QUOTED_LITERAL_PATTERN.match(arguments[1].strip())

        if literal:
            cubes.add(literal.group(1))

    return cubes
