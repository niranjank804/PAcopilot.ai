"""Recognise which of the standard TI process patterns a process implements.

Classification is rule-based and additive: a process scores against every
pattern and can match several, because real processes genuinely are several
things at once (an Oracle loader that also maintains a dimension, and logs).
Forcing a single label would throw away the second half of that sentence.

Scores are evidence counts normalised to 0..1, and every match carries the
evidence that produced it. A pattern claim you cannot justify to a TM1
developer is worse than no claim, so `PatternMatch.evidence` is not optional.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from src.tm1.ti.parser import ProcessRecord

Signal = Callable[[ProcessRecord], str | None]


@dataclass(frozen=True)
class Pattern:
    key: str
    name: str
    description: str
    signals: tuple[Signal, ...]
    # Evidence count below which a match is not reported at all.
    threshold: int = 2
    # A defining property the process must have before any signal is counted.
    # Without this, weak signals that several patterns share — "has parameters
    # and writes a cube" — are enough to clear the threshold on their own, and
    # a process with no ODBC datasource gets labelled an ODBC loader.
    gate: Signal | None = None


@dataclass
class PatternMatch:
    key: str
    name: str
    score: float
    evidence: list[str] = field(default_factory=list)


def _has_function(*names: str) -> Signal:
    wanted = {n.upper() for n in names}

    def signal(record: ProcessRecord) -> str | None:
        hits = sorted(wanted & set(record.functions_used))
        return f"calls {', '.join(hits)}" if hits else None

    return signal


def _datasource(*types: str) -> Signal:
    wanted = set(types)

    def signal(record: ProcessRecord) -> str | None:
        if record.datasource_type in wanted:
            return f"datasource is {record.datasource_type}"
        return None

    return signal


def _query_contains(*fragments: str) -> Signal:
    lowered = [f.lower() for f in fragments]

    def signal(record: ProcessRecord) -> str | None:
        query = record.datasource_query.lower()
        hits = [f for f in lowered if f in query]
        return f"SQL contains {', '.join(hits)}" if hits else None

    return signal


def _writes_cube() -> Signal:
    def signal(record: ProcessRecord) -> str | None:
        cubes = sorted(record.cubes_written)
        if not cubes:
            return None
        return f"writes to {', '.join(cubes[:3])}"

    return signal


def _reads_cube() -> Signal:
    def signal(record: ProcessRecord) -> str | None:
        cubes = sorted(record.cubes_read)
        return f"reads {', '.join(cubes[:3])}" if cubes else None

    return signal


def _flag(attribute: str, label: str) -> Signal:
    def signal(record: ProcessRecord) -> str | None:
        return label if getattr(record, attribute, False) else None

    return signal


def _name_contains(*fragments: str) -> Signal:
    lowered = [f.lower() for f in fragments]

    def signal(record: ProcessRecord) -> str | None:
        name = record.name.lower()
        hits = [f for f in lowered if f in name]
        return f"name contains '{hits[0]}'" if hits else None

    return signal


def _has_parameters() -> Signal:
    def signal(record: ProcessRecord) -> str | None:
        if not record.parameters:
            return None
        names = ", ".join(p["name"] for p in record.parameters[:4])
        return f"parameterised ({names})"

    return signal


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        key="oracle_loader",
        name="Relational (ODBC) Loader",
        description="Loads cube data from a relational source over ODBC.",
        signals=(
            _datasource("odbc"),
            _query_contains("select"),
            _writes_cube(),
            _has_parameters(),
            _name_contains("load", "oracle", "sql", "extract"),
        ),
        gate=_datasource("odbc"),
    ),
    Pattern(
        key="ascii_loader",
        name="Flat File (ASCII) Loader",
        description="Loads data or metadata from a delimited text file.",
        signals=(
            _datasource("ascii_delimited", "ascii", "ascii_fixed_width"),
            _writes_cube(),
            _has_parameters(),
            _name_contains("load", "import", "file", "csv"),
        ),
        gate=_datasource("ascii_delimited", "ascii", "ascii_fixed_width"),
    ),
    Pattern(
        key="cube_copy",
        name="Cube / Version Copy",
        description="Copies data between cubes, versions, or scenarios.",
        signals=(
            _datasource("cube_view"),
            _reads_cube(),
            _writes_cube(),
            _has_function("VIEWZEROOUT", "CUBECLEARDATA"),
            _name_contains("copy", "version", "scenario", "snapshot"),
        ),
        gate=lambda r: "reads and writes cubes" if (r.cubes_read and r.cubes_written) or r.datasource_type == "cube_view" else None,
    ),
    Pattern(
        key="dimension_maintenance",
        name="Dimension Maintenance",
        description="Creates or updates dimension elements and hierarchies.",
        signals=(
            _has_function(
                "DIMENSIONELEMENTINSERT",
                "DIMENSIONELEMENTCOMPONENTADD",
                "DIMENSIONELEMENTDELETE",
            ),
            _has_function("DIMENSIONCREATE", "DIMENSIONEXISTS"),
            _has_function("DIMENSIONDELETEALLELEMENTS"),
            _name_contains("dim", "hierarchy", "build"),
        ),
        gate=_has_function("DIMENSIONELEMENTINSERT", "DIMENSIONELEMENTCOMPONENTADD", "DIMENSIONELEMENTDELETE", "DIMENSIONCREATE", "DIMENSIONDELETEALLELEMENTS"),
    ),
    Pattern(
        key="subset_builder",
        name="Subset Builder",
        description="Builds static or MDX-driven subsets.",
        signals=(
            _has_function("SUBSETCREATE", "SUBSETCREATEBYMDX"),
            _has_function("SUBSETELEMENTINSERT", "SUBSETDELETEALLELEMENTS"),
            _has_function("SUBSETEXISTS", "SUBSETDESTROY"),
            _name_contains("subset"),
        ),
        gate=_has_function("SUBSETCREATE", "SUBSETCREATEBYMDX", "SUBSETELEMENTINSERT", "SUBSETMDXSET"),
    ),
    Pattern(
        key="attribute_loader",
        name="Attribute Loader",
        description="Populates element attributes.",
        signals=(
            _has_function("ATTRPUTS", "ATTRPUTN"),
            _has_function("ATTRINSERT"),
            _name_contains("attribute", "attr"),
        ),
        gate=_has_function("ATTRPUTS", "ATTRPUTN", "ATTRINSERT"),
    ),
    Pattern(
        key="allocation",
        name="Allocation / Spreading",
        description="Distributes values across a dimension using a driver.",
        signals=(
            _reads_cube(),
            _writes_cube(),
            _has_function("CELLINCREMENTN"),
            _name_contains("alloc", "spread", "driver", "distribut"),
        ),
        threshold=3,
        gate=lambda r: "reads and writes cubes" if r.cubes_read and r.cubes_written else None,
    ),
    Pattern(
        key="security",
        name="Security Maintenance",
        description="Maintains clients, groups, or element/cell security.",
        signals=(
            _flag("uses_security_functions", "uses security functions"),
            _has_function("SECURITYREFRESH"),
            _has_function("ELEMENTSECURITYPUT", "CELLSECURITYCUBECREATE"),
            _name_contains("security", "access", "group", "client"),
        ),
        gate=_flag("uses_security_functions", "uses security functions"),
    ),
    Pattern(
        key="export",
        name="Data Export",
        description="Writes cube or dimension content out to a file.",
        signals=(
            _has_function("ASCIIOUTPUT", "TEXTOUTPUT"),
            _datasource("cube_view", "dimension_subset"),
            _name_contains("export", "extract", "output", "unload"),
        ),
        gate=_has_function("ASCIIOUTPUT", "TEXTOUTPUT"),
    ),
    Pattern(
        key="audit_logging",
        name="Audit / Logging",
        description="Records run metadata for traceability.",
        signals=(
            _flag("uses_logging", "writes a log file"),
            _has_function("LOGOUTPUT"),
            _name_contains("log", "audit", "trace"),
        ),
        gate=_flag("uses_logging", "writes a log file"),
    ),
    Pattern(
        key="error_handling",
        name="Explicit Error Handling",
        description="Detects bad input and fails or rejects deliberately.",
        signals=(
            _flag("uses_error_handling", "uses error-handling functions"),
            _has_function("ITEMREJECT", "ITEMSKIP"),
            _has_function("PROCESSERROR", "PROCESSQUIT", "PROCESSBREAK"),
        ),
        gate=_flag("uses_error_handling", "uses error-handling functions"),
    ),
    Pattern(
        key="performance_tuned",
        name="Performance Tuned",
        description="Uses bulk load, logging control, or view extract tuning.",
        signals=(
            _has_function("ENABLEBULKLOADMODE", "DISABLEBULKLOADMODE"),
            _has_function("CUBESETLOGCHANGES"),
            _has_function(
                "VIEWEXTRACTSKIPCALCSSET",
                "VIEWEXTRACTSKIPRULEVALUESSET",
                "VIEWEXTRACTSKIPZEROESSET",
            ),
        ),
        threshold=1,
        gate=lambda r: "uses performance functions" if r.performance_functions else None,
    ),
    Pattern(
        key="cleanup",
        name="Temporary Object Cleanup",
        description="Destroys the temporary views/subsets it created.",
        signals=(
            _flag("has_cleanup", "destroys objects in Epilog"),
            _has_function("VIEWDESTROY", "SUBSETDESTROY"),
        ),
        threshold=1,
        gate=_has_function("VIEWDESTROY", "SUBSETDESTROY"),
    ),
)


def classify(record: ProcessRecord, *, minimum_score: float = 0.0) -> list[PatternMatch]:
    """Return every pattern the process matches, strongest first."""

    matches: list[PatternMatch] = []

    for pattern in PATTERNS:
        if pattern.gate is not None and pattern.gate(record) is None:
            continue

        evidence = [
            result
            for signal in pattern.signals
            if (result := signal(record)) is not None
        ]

        if len(evidence) < pattern.threshold:
            continue

        score = len(evidence) / len(pattern.signals)

        if score < minimum_score:
            continue

        matches.append(
            PatternMatch(
                key=pattern.key,
                name=pattern.name,
                score=round(score, 3),
                evidence=evidence,
            )
        )

    matches.sort(key=lambda m: (-m.score, m.key))
    return matches


def pattern_index(records: Iterable[ProcessRecord]) -> dict[str, list[str]]:
    """Map pattern key -> process names, for 'show me a reference example'."""

    index: dict[str, list[str]] = {}

    for record in records:
        for match in classify(record):
            index.setdefault(match.key, []).append(record.name)

    return index
