"""TM1 function reference: lookup and static validation of generated code.

The reference is a static library of documented TM1 functions, each tagged with
the contexts it is valid in (TI / Rules / Excel) and the server versions that
support it. Two things it gives us that a compile check cannot:

  * Rules and feeders have no TM1 dry-run, so this is the only pre-execution
    check available for them.
  * A v11-only function is a runtime failure on a v12 server (Planning
    Analytics SaaS), and models trained on older TM1 material emit them
    readily — CubeSaveData, SaveDataAll, ExecuteCommand and friends.

Deliberately conservative: findings are reported only where the library gives
positive evidence about a function it actually knows. A function that isn't in
the library is never reported, because the library documents public functions
and cannot prove absence.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "tm1_functions.json"

VALID_CONTEXTS = ("TI", "Rules", "Excel")
VALID_VERSIONS = ("v11", "v12")

# Language constructs, not functions. Those that take a parenthesised
# condition look exactly like a call to the scanner, and only some of them
# appear in the function library — ELSEIF( is ordinary TI and is not in it.
# Excluded from the unknown-function check only; context and version checks
# still apply to any of these the library does document.
_LANGUAGE_KEYWORDS = frozenset(
    {
        "IF",
        "ELSEIF",
        "ELSE",
        "ENDIF",
        "WHILE",
        "END",
        "BREAK",
        "CONTINUE",
        "RETURN",
    }
)


class TM1Function:

    __slots__ = ("name", "description", "contexts", "versions", "url")

    def __init__(self, name: str, description: str, contexts, versions, url: str):
        self.name = name
        self.description = description
        self.contexts = tuple(contexts)
        self.versions = tuple(versions)
        self.url = url

    def supports_context(self, context: str) -> bool:
        return context in self.contexts

    def supports_version(self, version: str) -> bool:
        return version in self.versions

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "contexts": list(self.contexts),
            "versions": list(self.versions),
            "url": self.url,
        }


# Descriptions the upstream library states incorrectly. These are served to
# the code agents as authoritative and carry a source URL, so a wrong one is
# worse than no answer at all — a reviewer is less likely to doubt a cited
# claim. Corrections live here rather than in the JSON so that regenerating
# the data file from a fresh scrape cannot silently reintroduce them, and so
# that every deviation from the source is visible in one place.
#
# Each was verified against the function's own behaviour:
#   HierarchyAttrPutN/PutS - upstream has the numeric and string variants
#     swapped; following it writes numeric data through the string function.
#   LN - upstream prepends ABS's description to LN's.
#   ElementAttrPutS - upstream says "from"; the Put* functions write.
_DESCRIPTION_CORRECTIONS = {
    "HIERARCHYATTRPUTN": (
        "Uploads data to a numeric attribute for a dimension's hierarchy."
    ),
    "HIERARCHYATTRPUTS": (
        "Uploads data to a string attribute for a dimension's hierarchy."
    ),
    "LN": "Returns the natural (base e) logarithm of a number.",
    "ELEMENTATTRPUTS": (
        "Uploads data to a string attribute for an element."
    ),
}


@lru_cache(maxsize=1)
def _library() -> dict[str, TM1Function]:
    """Function name (upper-cased) -> TM1Function. Loaded once per process."""

    with _DATA_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    return {
        key: TM1Function(
            name=entry["name"],
            description=_DESCRIPTION_CORRECTIONS.get(
                key, entry.get("description", "")
            ),
            contexts=entry.get("contexts", []),
            versions=entry.get("versions", []),
            url=entry.get("url", ""),
        )
        for entry in payload["functions"]
        for key in (entry["name"].upper(),)
    }


def function_count() -> int:
    return len(_library())


def lookup(name: str) -> TM1Function | None:
    """Exact lookup. TM1 function names are case-insensitive."""

    if not name:
        return None

    return _library().get(name.strip().upper())


def search(query: str, limit: int = 15) -> list[TM1Function]:
    """Name-prefix and description search, best matches first."""

    if not query or not query.strip():
        return []

    needle = query.strip().lower()
    exact: list[TM1Function] = []
    prefix: list[TM1Function] = []
    contains: list[TM1Function] = []
    described: list[TM1Function] = []

    for function in _library().values():
        lowered = function.name.lower()

        if lowered == needle:
            exact.append(function)
        elif lowered.startswith(needle):
            prefix.append(function)
        elif needle in lowered:
            contains.append(function)
        elif needle in function.description.lower():
            described.append(function)

    ordered = (
        exact
        + sorted(prefix, key=lambda f: f.name)
        + sorted(contains, key=lambda f: f.name)
        + sorted(described, key=lambda f: f.name)
    )

    return ordered[:limit]


# A bare identifier followed by "(" is the only reliable signal of a call in
# TI/rules source. Anchored on a non-word char so 'MyCubeSaveData(' can't match
# 'CubeSaveData'.
_CALL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)\s*\(")

# TI also lets a function stand alone as a statement, with no parentheses at
# all — 'SaveDataAll;', 'ItemSkip;', 'SecurityRefresh;'. That is the idiomatic
# form, and several of them are exactly the v11-only functions the version
# check exists to catch, so matching only 'Name(' missed them entirely.
#
# Resolved against the library rather than accepted on sight: a bare
# identifier before a semicolon is far more often a variable than a call, and
# only a documented function name can be checked for context or version
# anyway.
_STATEMENT_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)\s*;")

# TM1 line comments run to end of line; string literals are single-quoted with
# '' as the escape. Both are blanked before scanning so a function name inside
# a comment or a string is never treated as a call.
#
# These MUST be one alternation scanned left to right, string branch first —
# not two passes. '#' is ordinary inside a TM1 string ('#,##0' masks, '#All'
# element names, 'Rec #' labels), so a comment-first pass would treat it as a
# comment, blank the rest of the line including the closing quote, and break
# quote parity for everything after it. That both fabricates calls out of
# later string contents and hides real ones.
_NOISE_PATTERN = re.compile(
    r"'(?:[^']|'')*'"  # single-quoted literal, '' escape — wins over '#'
    r"|#[^\n]*"  # line comment, only when not inside a literal
)


def _article(word: str) -> str:
    return "an" if word[:1].upper() in "AEIOU" else "a"


def _strip_noise(code: str) -> str:
    """Blank out comments and string literals, preserving line numbers."""

    def blank(match: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _NOISE_PATTERN.sub(blank, code)


def _at_statement_start(cleaned: str, position: int) -> bool:
    """True when only whitespace separates `position` from the previous ';'.

    Keeps a right-hand-side read — 'sChar = DatasourceASCIIDelimiter;' — from
    being counted as an invocation.
    """

    index = position - 1

    while index >= 0 and cleaned[index] in " \t":
        index -= 1

    return index < 0 or cleaned[index] in ";\n"


def find_calls(code: str) -> list[tuple[str, int]]:
    """(function name, 1-based line number) for every call site in `code`.

    Covers both 'Name(...)' and the parenthesis-less statement form 'Name;'.
    The latter is only reported for names the library documents — see
    _STATEMENT_PATTERN.
    """

    if not code:
        return []

    cleaned = _strip_noise(code)
    library = _library()
    calls: list[tuple[str, int]] = []

    for match in _CALL_PATTERN.finditer(cleaned):
        line = cleaned.count("\n", 0, match.start()) + 1
        calls.append((match.group(1), line))

    for match in _STATEMENT_PATTERN.finditer(cleaned):
        name = match.group(1)

        if name.upper() in _LANGUAGE_KEYWORDS or name.upper() not in library:
            continue

        if not _at_statement_start(cleaned, match.start()):
            continue

        line = cleaned.count("\n", 0, match.start()) + 1
        calls.append((name, line))

    return calls


def validate_code(
    code: str,
    *,
    context: str,
    version: str | None = None,
    report_unknown: bool = False,
) -> list[dict]:
    """Report function-usage problems in TI or rule source.

    `context` is 'TI' or 'Rules'; `version` is 'v11' or 'v12' when the target
    server version is known.

    Errors are raised only for functions the library positively identifies —
    a wrong context or an unsupported version.

    `report_unknown` additionally emits a *warning* for each call the library
    does not recognise. This is off by default because the library documents
    public functions and cannot prove absence, so an unrecognised name is a
    prompt to verify rather than proof of a mistake. It is worth enabling for
    rules and feeders, where TM1 offers no compile check at all and an
    invented function would otherwise surface only at execution.
    """

    if context not in VALID_CONTEXTS:
        raise ValueError(f"context must be one of {VALID_CONTEXTS}, got {context!r}")

    # An unrecognised version would otherwise match no function's version list
    # and flag every documented call in the file. Fail loudly instead.
    if version is not None and version not in VALID_VERSIONS:
        raise ValueError(
            f"version must be one of {VALID_VERSIONS} or None, got {version!r}"
        )

    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for name, line in find_calls(code):
        function = lookup(name)

        if function is None:
            if report_unknown and name.upper() not in _LANGUAGE_KEYWORDS:
                key = (name.upper(), "unknown")
                if key not in seen:
                    seen.add(key)
                    issues.append(
                        {
                            "function": name,
                            "line": line,
                            "severity": "warning",
                            "kind": "unknown",
                            "message": (
                                f"{name} is not in the TM1 function reference. "
                                "Confirm it is a real function and spelled "
                                "correctly — the reference covers documented "
                                "functions, so this is a prompt to verify "
                                "rather than proof it does not exist."
                            ),
                            "url": "",
                        }
                    )
            continue

        if not function.supports_context(context):
            key = (function.name.upper(), "context")
            if key not in seen:
                seen.add(key)
                issues.append(
                    {
                        "function": function.name,
                        "line": line,
                        "severity": "error",
                        "kind": "context",
                        "message": (
                            f"{function.name} is not valid in {context} — it is "
                            f"{_article(function.contexts[0])} "
                            f"{'/'.join(function.contexts)} function."
                        ),
                        "url": function.url,
                    }
                )

        if version and not function.supports_version(version):
            key = (function.name.upper(), "version")
            if key not in seen:
                seen.add(key)
                issues.append(
                    {
                        "function": function.name,
                        "line": line,
                        "severity": "error",
                        "kind": "version",
                        "message": (
                            f"{function.name} is not available on {version} — it is "
                            f"supported on {', '.join(function.versions)} only."
                        ),
                        "url": function.url,
                    }
                )

    return issues


def validate_process(
    sections: dict[str, str],
    *,
    version: str | None = None,
    report_unknown: bool = False,
) -> list[dict]:
    """Validate the TI sections of a process draft.

    `sections` maps prolog/metadata/data/epilog to their source. Each issue is
    tagged with the section it came from.
    """

    issues: list[dict] = []

    for section in ("prolog", "metadata", "data", "epilog"):
        source = sections.get(section)

        if not source:
            continue

        for issue in validate_code(
            source,
            context="TI",
            version=version,
            report_unknown=report_unknown,
        ):
            issues.append({**issue, "section": section})

    return issues
