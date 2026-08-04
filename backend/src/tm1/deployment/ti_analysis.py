"""Static analysis of drafted TurboIntegrator code.

Runs alongside the server-side dry-run compile in `change_service`, not
instead of it. The dry-run is authoritative for syntax, but the defects
that actually reach reviewers are semantic:

* **Undefined identifiers.** The generating agent invents friendly-named
  datasource variables (`Organization`, `Years`, `vCashFlow_Direct_`)
  and reads them in the Data tab. TI never creates those — only the
  columns declared in `variables` exist — so the process either fails to
  compile or silently reads an empty string. The compiler reports this
  at the use site, which reads like a typo rather than a missing
  declaration.
* **Inconsistent capitalisation** of a name between its declaration and
  its uses, which the organization's own standards forbid.

Both are reported as ordinary entries in a draft's `validation_errors`,
so an affected draft cannot be executed until it is re-proposed.

The identifier check works off a symbol table rather than a TI grammar.
Anything *called* (an identifier immediately followed by `(`) is treated
as a function and ignored, which covers TM1's several hundred builtins
without enumerating them. That leaves only bare reads to resolve
against declared parameters, declared datasource columns, names assigned
anywhere in the process, and the reserved words below.

A false positive here blocks a legitimate draft, so RESERVED_NAMES is
deliberately broad and every rule fires only on evidence in the draft
itself.
"""

import re

CODE_TABS = ("prolog", "metadata", "data", "epilog")

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SOURCE_COLUMN = re.compile(r"^v[1-9][0-9]*$")

# Names that legitimately appear bare (not as a call) in TI. Lower-cased
# because TI resolves all of these case-insensitively.
RESERVED_NAMES = frozenset(
    name.lower()
    for name in (
        # Control flow
        "If", "Else", "ElseIf", "EndIf", "While", "End", "Break",
        "Continue", "Return", "Then", "Do",
        # Flow-control statements, valid with or without parentheses
        "ItemSkip", "ItemReject", "ProcessBreak", "ProcessQuit",
        "ProcessError", "ProcessExitNormal", "ProcessExitByChoreQuit",
        # Reserved variables TI populates for a view/ODBO datasource
        "NValue", "SValue", "Value_Is_String",
        # Datasource globals, assignable and readable in the Prolog
        "DatasourceType", "DatasourceNameForServer",
        "DatasourceNameForClient", "DatasourceUsername",
        "DatasourcePassword", "DatasourceQuery", "DatasourceCubeview",
        "DatasourceDimensionSubset", "DatasourceASCIIDelimiter",
        "DatasourceASCIIQuoteCharacter", "DatasourceASCIIDecimalSeparator",
        "DatasourceASCIIThousandSeparator", "DatasourceASCIIHeaderRecords",
        "DatasourceODBOCatalog", "DatasourceODBOConnectionString",
        "DatasourceODBOCubeName", "DatasourceODBOHierarchyName",
        "DatasourceODBOLocation", "DatasourceODBOProvider",
        "DatasourceODBOSAPClientID", "DatasourceODBOSAPClientLanguage",
        # Error-handling globals
        "OnMinorErrorDoItemSkip", "MinorErrorLogMax",
        # Type keywords used in declarations
        "Numeric", "String",
    )
)


def _strip_noise(line: str) -> str:
    """Blank out string literals and trailing comments on one TI line.

    Identifiers inside a quoted string (element names, log text) are data,
    not variable references, and a '#' inside a string does not start a
    comment. Both would otherwise pollute the symbol table.
    """

    out: list[str] = []
    in_string = False
    index = 0

    while index < len(line):
        char = line[index]

        if in_string:
            if char == "'":
                # '' is an escaped quote *inside* a TI string, not a close.
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 2
                    continue

                in_string = False

            index += 1
            continue

        if char == "'":
            in_string = True
            out.append(" ")
            index += 1
            continue

        if char == "#":
            break

        out.append(char)
        index += 1

    return "".join(out)


def _statements(content: dict) -> list[tuple[str, str]]:
    """(tab, statement) for every ';'-delimited statement in the process."""

    statements: list[tuple[str, str]] = []

    for tab in CODE_TABS:
        code = content.get(tab)

        if not code:
            continue

        for raw in str(code).splitlines():
            cleaned = _strip_noise(raw)

            statements.extend(
                (tab, part) for part in cleaned.split(";") if part.strip()
            )

    return statements


def _names_from(content: dict, key: str) -> set[str]:
    names = set()

    for item in content.get(key) or []:
        if not isinstance(item, dict):
            continue

        name = item.get("name")

        if name:
            names.add(str(name))

    return names


def _undefined_errors(
    statements: list[tuple[str, str]],
    known_lower: set[str],
    has_variables: bool,
) -> list[str]:

    # tab -> {lowered: original spelling}, first sighting wins for the
    # message so the reported spelling is the one the author wrote.
    undefined: dict[str, dict[str, str]] = {}

    for tab, statement in statements:
        called = {match.lower() for match in _CALL.findall(statement)}

        for token in _IDENTIFIER.findall(statement):
            lowered = token.lower()

            if lowered in called or lowered in known_lower:
                continue

            if lowered in RESERVED_NAMES:
                continue

            undefined.setdefault(tab, {}).setdefault(lowered, token)

    errors = []

    for tab in CODE_TABS:
        found = undefined.get(tab)

        if not found:
            continue

        names = ", ".join(sorted(found.values()))
        source_like = [n for n in found if _SOURCE_COLUMN.match(n)]

        if source_like and not has_variables:
            errors.append(
                f"{tab.capitalize()} reads source columns ({names}) but the "
                "process declares no datasource variables. Declare them in "
                "'variables' and set datasource_type to 'ASCII'."
            )
        else:
            errors.append(
                f"{tab.capitalize()} reads undefined name(s): {names}. Every "
                "name must be a declared parameter, a declared datasource "
                "column in 'variables', or assigned earlier in the process — "
                "TI does not create variables from column headings."
            )

    return errors


def _case_errors(
    spellings_by_name: dict[str, set[str]],
    declared: dict[str, str],
    assigned: set[str],
) -> list[str]:

    errors = []

    for lowered, spellings in sorted(spellings_by_name.items()):
        if len(spellings) < 2:
            continue

        # `nValue = NValue;` is idiomatic TI: a local differing only in case
        # from a reserved name is legal and common, so reserved names are
        # never a casing defect.
        if lowered in RESERVED_NAMES:
            continue

        # TI function names are genuinely case-insensitive and are written
        # in mixed case all over real TM1 code, so a mixed-case group is
        # only a defect when the name is one this process declares or
        # assigns.
        canonical = declared.get(lowered)

        if canonical is None and not (spellings & assigned):
            continue

        used = ", ".join(sorted(spellings))

        if canonical is not None:
            errors.append(
                f"Variable '{canonical}' is declared once but referenced "
                f"with inconsistent capitalisation ({used}). Use "
                f"'{canonical}' everywhere."
            )
        else:
            errors.append(
                f"Variable '{sorted(spellings)[0]}' is referenced with "
                f"inconsistent capitalisation ({used}). Pick one spelling "
                "and use it consistently."
            )

    return errors


# Datasource types whose source variables we can enumerate: 'None' has
# none, and 'ASCII' declares them in `variables`. Anything else — most
# importantly a cube view — has variables TM1 generates from the source's
# own shape (one per dimension, plus a value), which never appear in
# `variables` and cannot be derived from the draft.
_ENUMERABLE_DATASOURCES = frozenset({"none", "ascii"})


def analyze(content: dict | None, datasource_type: str | None = None) -> list[str]:
    """Return validation errors for a proposed process, empty if clean.

    `datasource_type` is the process's *effective* datasource — from the
    draft when it sets one, otherwise from the version already on the
    server. Undefined-name checking only runs when that datasource lets us
    enumerate the source variables; on a cube view every `dVersion`,
    `dPeriod`, `dValue` would otherwise be reported as undefined and a
    perfectly good draft would be blocked. Casing checks run regardless.
    """

    if not content:
        return []

    statements = _statements(content)

    declared_names = _names_from(content, "parameters") | _names_from(
        content, "variables"
    )
    declared = {name.lower(): name for name in declared_names}

    assigned: set[str] = set()
    spellings_by_name: dict[str, set[str]] = {}

    # A declaration is itself a use of the name: 'pSourceFile' declared and
    # only ever written 'psourcefile' in code is exactly the casing defect,
    # and the code alone shows one spelling.
    for name in declared_names:
        spellings_by_name.setdefault(name.lower(), set()).add(name)

    for _tab, statement in statements:
        match = _ASSIGNMENT.match(statement)

        if match:
            assigned.add(match.group(1))

        for token in _IDENTIFIER.findall(statement):
            spellings_by_name.setdefault(token.lower(), set()).add(token)

    # Every assignment anywhere counts, not just ones textually above the
    # read. Order-sensitivity would turn a forward reference into a false
    # positive, and a blocked legitimate draft costs more than a missed one.
    known_lower = set(declared) | {name.lower() for name in assigned}

    effective_datasource = (
        content.get("datasource_type") or datasource_type or "None"
    )

    undefined: list[str] = []

    if str(effective_datasource).lower() in _ENUMERABLE_DATASOURCES:
        undefined = _undefined_errors(
            statements, known_lower, bool(content.get("variables"))
        )

    return undefined + _case_errors(spellings_by_name, declared, assigned)
