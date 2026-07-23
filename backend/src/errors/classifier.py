import re
from dataclasses import dataclass

# Ordered: first match wins, most specific patterns first. This is a cheap,
# deterministic first pass — the troubleshooter agent still investigates the
# real objects before explaining anything, this just labels severity/type
# for the UI without waiting on an LLM round trip.
_PATTERNS: list[tuple[str, str, str]] = [
    (
        "recursion",
        r"(recursion level too deep|stack overflow|circular reference)",
        "high",
    ),
    (
        "data_directory",
        r"((data|database) directory (not found|is invalid)|cannot find.*data ?base)",
        "critical",
    ),
    (
        "feeder_overflow",
        r"(feeder|too many .*leaf cells|feeder statement.*overflow)",
        "medium",
    ),
    (
        "authentication",
        r"(could not log ?on|authentication failed|invalid credentials|unauthorized)",
        "high",
    ),
    (
        "process_failure",
        r"(ti process failed|process execution error|processbreak|minorerrorcount)",
        "medium",
    ),
    (
        "rule_error",
        r"(rule compilation error|error .*rule line|syntax error.*rule)",
        "medium",
    ),
    (
        "memory",
        r"(out of memory|memory allocation failed|insufficient memory)",
        "critical",
    ),
    (
        "lock",
        r"(deadlock|lock timeout|could not acquire lock)",
        "medium",
    ),
]


@dataclass(frozen=True)
class ErrorClassification:
    error_type: str
    severity: str


def classify_error(error_text: str) -> ErrorClassification:
    for error_type, pattern, severity in _PATTERNS:
        if re.search(pattern, error_text, re.IGNORECASE):
            return ErrorClassification(error_type=error_type, severity=severity)

    return ErrorClassification(error_type="unknown", severity="unknown")
