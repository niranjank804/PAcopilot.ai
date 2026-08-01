"""Evaluation case schema and loader.

A case is a prompt, the checks its answer must satisfy, and the metadata
needed to interpret a failure: how bad it is, which TM1 versions it applies
to, and what it is a regression against.

Severity exists because a pass rate that counts every failure equally is
not a quality signal. An invented TI function and an unidiomatic variable
name are not the same event, and a suite that averages them produces a
number nobody can act on.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CASES_ROOT = Path(__file__).resolve().parent / "cases"

# Ordered worst-first. The weights set how much each failure costs a run's
# score; a single CRITICAL failure should dominate any number of LOW ones,
# because shipping an invented function is not offset by good formatting.
SEVERITY_WEIGHTS = {
    "critical": 100,
    "high": 20,
    "medium": 5,
    "low": 1,
}

VALID_SEVERITIES = tuple(SEVERITY_WEIGHTS)

# Which severity a failing check carries when the case does not say.
# Anything the function library can prove wrong is critical: those are
# statements of fact, not matters of style.
DEFAULT_SEVERITY = {
    "functions_are_real": "critical",
    "absent": "high",
    "qualified": "high",
    "present": "medium",
}


@dataclass
class EvalCase:
    name: str
    prompt: str
    path: Path
    description: str = ""
    agent: str | None = None
    checks: dict = field(default_factory=dict)
    severity: dict = field(default_factory=dict)
    supported_versions: list[str] = field(default_factory=list)
    unsupported_versions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    manual_review: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        """The cases/<domain>/ folder this case lives in — ti, rules, mdx."""

        return self.path.parent.name

    @property
    def golden_path(self) -> Path:
        return self.path.with_suffix("").with_suffix(".golden.md")

    def golden(self) -> str | None:
        path = self.golden_path

        return path.read_text(encoding="utf-8") if path.exists() else None

    def severity_of(self, check_name: str) -> str:
        """Severity for a failing check — case override, else the default."""

        # check_qualified reports as 'qualified:PositionDelimited'.
        base = check_name.split(":", 1)[0]

        return self.severity.get(
            check_name, self.severity.get(base, DEFAULT_SEVERITY.get(base, "medium"))
        )


def _require(payload: dict, key: str, path: Path):
    if key not in payload:
        raise ValueError(f"{path}: missing required field {key!r}")

    return payload[key]


def load_case(path: Path) -> EvalCase:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    severity = payload.get("severity") or {}

    for check_name, level in severity.items():
        if level not in VALID_SEVERITIES:
            # A typo here would silently downgrade a critical check, so it
            # fails at load rather than at scoring time.
            raise ValueError(
                f"{path}: severity for {check_name!r} is {level!r}, "
                f"expected one of {VALID_SEVERITIES}"
            )

    return EvalCase(
        name=_require(payload, "name", path),
        prompt=_require(payload, "prompt", path),
        path=path,
        description=payload.get("description", ""),
        agent=payload.get("agent"),
        checks=payload.get("checks") or {},
        severity=severity,
        supported_versions=payload.get("supported_versions") or [],
        unsupported_versions=payload.get("unsupported_versions") or [],
        tags=payload.get("tags") or [],
        manual_review=payload.get("manual_review") or [],
    )


def load_cases(root: Path | None = None, domain: str | None = None) -> list[EvalCase]:
    root = root or CASES_ROOT
    pattern = f"{domain}/*.yaml" if domain else "*/*.yaml"

    return sorted(
        (load_case(path) for path in root.glob(pattern)),
        key=lambda case: (case.domain, case.name),
    )
