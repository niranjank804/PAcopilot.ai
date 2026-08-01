"""Infer a team's actual TM1 coding conventions from their own processes.

This is the "coding DNA" layer. Every rule it emits is a measured majority
over the parsed corpus, carrying the sample size and the counter-examples —
so a generator can say "your team prefixes parameters with `p` (61 of 64
processes)" instead of asserting a house style nobody agreed to.

Confidence is the share of the corpus that agrees, damped by sample size.
A 3-of-3 observation is unanimous but weak evidence; without damping it
would outrank a 55-of-64 majority, and the generator would then enforce a
convention inferred from three files.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from src.tm1.ti.parser import _NOISE, SECTIONS, ProcessRecord, _mask

# Sample size at which confidence reaches ~90% of the raw agreement ratio.
_DAMPING = 5

_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def _has_inline_comment(code: str) -> bool:
    """True when a comment trails executable code on the same line.

    Detection runs against the masked copy so that a '#' inside a string
    literal (`'#,##0'` is a common TM1 format mask) is not read as the start
    of a comment. A line that is *only* a comment is not an inline comment
    however long its decoration — `# ==== SECTION ====` is a header, and
    counting it as a violation is how a clean codebase gets marked dirty.
    """

    masked = _mask(code)

    # _NOISE alternates literals and comments left to right, so a match that
    # starts with '#' is a genuine comment and one that starts with a quote
    # is a literal. That distinction is not recoverable from the mask alone,
    # since both blank to spaces.
    for match in _NOISE.finditer(code):
        if not match.group(0).startswith("#"):
            continue

        line_start = code.rfind("\n", 0, match.start()) + 1

        if masked[line_start : match.start()].strip():
            return True

    return False


@dataclass
class Convention:
    key: str
    statement: str
    confidence: float
    support: int
    sample: int
    examples: list[str] = field(default_factory=list)
    counter_examples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "statement": self.statement,
            "confidence": self.confidence,
            "support": self.support,
            "sample": self.sample,
            "examples": self.examples[:5],
            "counter_examples": self.counter_examples[:5],
        }


@dataclass
class CodingDNA:
    process_count: int = 0
    conventions: list[Convention] = field(default_factory=list)
    naming: dict[str, object] = field(default_factory=dict)
    section_usage: dict[str, float] = field(default_factory=dict)
    common_functions: list[tuple[str, int]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "process_count": self.process_count,
            "conventions": [c.as_dict() for c in self.conventions],
            "naming": self.naming,
            "section_usage": self.section_usage,
            "common_functions": self.common_functions,
        }

    def enforced(self, minimum_confidence: float = 0.6) -> list[Convention]:
        """Conventions strong enough to hold a generated process to."""

        return [c for c in self.conventions if c.confidence >= minimum_confidence]


def _confidence(support: int, sample: int) -> float:
    if sample == 0:
        return 0.0

    ratio = support / sample
    damped = ratio * (sample / (sample + _DAMPING))
    return round(damped, 3)


def _observe(
    key: str,
    statement: str,
    records: Sequence[ProcessRecord],
    holds,
    *,
    applies=None,
) -> Convention | None:
    """Measure how consistently `holds` is true across the corpus.

    `applies` narrows the sample to processes where the rule is meaningful —
    a convention about SQL parameters says nothing about a file loader, and
    counting those as violations would understate a real, consistent habit.
    """

    considered = [r for r in records if applies is None or applies(r)]

    if not considered:
        return None

    agreeing = [r for r in considered if holds(r)]
    disagreeing = [r for r in considered if not holds(r)]

    return Convention(
        key=key,
        statement=statement,
        confidence=_confidence(len(agreeing), len(considered)),
        support=len(agreeing),
        sample=len(considered),
        examples=[r.name for r in agreeing if r.name],
        counter_examples=[r.name for r in disagreeing if r.name],
    )


def _prefix_of(name: str) -> str:
    """Leading lowercase run, the usual TM1 Hungarian-ish marker (`pMonth`)."""

    match = re.match(r"^([a-z]+)(?=[A-Z0-9_])", name)
    return match.group(1) if match else ""


def _name_separator(names: Iterable[str]) -> str:
    counts = Counter()

    for name in names:
        if " - " in name:
            counts[" - "] += 1
        elif "_" in name:
            counts["_"] += 1
        elif "." in name:
            counts["."] += 1

    return counts.most_common(1)[0][0] if counts else ""


def infer_conventions(records: Sequence[ProcessRecord]) -> CodingDNA:
    """Derive the team's conventions from parsed processes."""

    dna = CodingDNA(process_count=len(records))

    if not records:
        return dna

    parameter_names = [p["name"] for r in records for p in r.parameters]
    prefix_counts = Counter(
        prefix for name in parameter_names if (prefix := _prefix_of(name))
    )
    dominant_prefix = prefix_counts.most_common(1)[0][0] if prefix_counts else ""

    separator = _name_separator(r.name for r in records if r.name)

    process_words = Counter()
    for record in records:
        head = _WORD_SPLIT.split(record.name)[0] if record.name else ""
        if head:
            process_words[head] += 1

    dna.naming = {
        "process_name_separator": separator,
        "process_name_prefixes": process_words.most_common(8),
        "parameter_prefix": dominant_prefix,
        "parameter_prefix_counts": prefix_counts.most_common(5),
    }

    function_counts: Counter = Counter()
    for record in records:
        for function, count in record.functions_used.items():
            function_counts[function] += count
    dna.common_functions = function_counts.most_common(30)

    for section in SECTIONS:
        used = sum(1 for r in records if r.line_counts.get(section, 0) > 3)
        dna.section_usage[section] = round(used / len(records), 3)

    candidates = [
        _observe(
            "parameter_prefix",
            f"Process parameters are prefixed with '{dominant_prefix}' "
            f"(for example {dominant_prefix}Month, {dominant_prefix}Year).",
            records,
            lambda r: all(
                _prefix_of(p["name"]) == dominant_prefix for p in r.parameters
            ),
            applies=lambda r: bool(r.parameters) and bool(dominant_prefix),
        ),
        _observe(
            "process_name_separator",
            f"Process names separate their parts with '{separator}' "
            "(for example 'DATA - Load - Oracle').",
            records,
            lambda r: separator in r.name,
            applies=lambda r: bool(r.name) and bool(separator),
        ),
        _observe(
            "header_comment",
            "Every process opens with a header comment block describing its "
            "purpose before any executable statement.",
            records,
            lambda r: bool(r.prolog.lstrip().startswith("#") or r.header_comment),
            applies=lambda r: r.line_counts.get("prolog", 0) > 3,
        ),
        _observe(
            "no_inline_comments",
            "Comments sit on their own line above the code they describe, "
            "never trailing on the same line as a statement.",
            records,
            lambda r: not any(_has_inline_comment(getattr(r, s)) for s in SECTIONS),
        ),
        _observe(
            "error_handling",
            "Processes validate their inputs and fail deliberately using "
            "ProcessError / ProcessQuit rather than running on bad data.",
            records,
            lambda r: r.uses_error_handling,
        ),
        _observe(
            "logging",
            "Processes write an execution log so a run can be traced after "
            "the fact.",
            records,
            lambda r: r.uses_logging,
        ),
        _observe(
            "cleanup",
            "Temporary views and subsets created by a process are destroyed "
            "in the Epilog.",
            records,
            lambda r: r.has_cleanup,
            applies=lambda r: bool(r.temporary_objects)
            or any(o.access == "create" for o in r.objects),
        ),
        _observe(
            "prolog_validation",
            "Parameter validation happens in the Prolog, before any data is "
            "touched.",
            records,
            lambda r: any(
                function in r.prolog.upper()
                for function in ("PROCESSQUIT", "PROCESSERROR", "PROCESSBREAK")
            ),
            applies=lambda r: bool(r.parameters),
        ),
        _observe(
            "parameterised_sql",
            "SQL statements bind process parameters with ?parameter? "
            "substitution instead of concatenating literals.",
            records,
            lambda r: "?" in r.datasource_query,
            applies=lambda r: r.datasource_type == "odbc"
            and bool(r.datasource_query),
        ),
        _observe(
            "metadata_section_used",
            "Dimension and element maintenance is done in the Metadata tab, "
            "not the Data tab.",
            records,
            lambda r: r.line_counts.get("metadata", 0) > 3,
            applies=lambda r: any(
                f.startswith("DIMENSIONELEMENT") for f in r.functions_used
            ),
        ),
    ]

    dna.conventions = [c for c in candidates if c is not None]
    dna.conventions.sort(key=lambda c: -c.confidence)

    return dna
