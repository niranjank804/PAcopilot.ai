"""Measure quality signals so gates can be set from data, not guesses.

Emits one JSON artifact per run and appends a row to a history file. The
point is the trend: a threshold picked before you know the current number
is either meaningless or blocks everything, and a coverage figure with no
history cannot tell you whether a PR made things worse.

Nothing here fails a build. It measures; `--check` compares against a
recorded floor once you have enough history to choose one.

    python scripts/quality_report.py                 # measure and print
    python scripts/quality_report.py --json out.json # artifact for CI
    python scripts/quality_report.py --check         # enforce the floor
"""

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_XML = BACKEND_ROOT / "coverage.xml"
HISTORY = BACKEND_ROOT / ".quality-history.jsonl"
FLOOR_FILE = BACKEND_ROOT / ".coverage-floor.json"

# Paths in coverage.xml are relative to the source root, so these are
# prefixes below src/, not full repository paths.
CRITICAL_MODULES = {
    "auth_and_tokens": (
        "services/auth_service",
        "services/jwt_service",
        "services/token_revocation_service",
        "api/dependencies/",
    ),
    "ai_orchestration": ("ai/",),
    "tm1_integration": ("tm1/",),
    "deployments": ("tm1/deployment/",),
    "knowledge": ("knowledge/",),
}


def _coverage_by_file() -> list[tuple[str, int, int]]:
    if not COVERAGE_XML.exists():
        raise SystemExit(
            f"{COVERAGE_XML.name} not found — run pytest with --cov-report=xml first."
        )

    root = ET.parse(COVERAGE_XML).getroot()
    files = []

    for cls in root.iter("class"):
        name = (cls.get("filename") or "").replace("\\", "/")
        lines = cls.find("lines")

        if lines is None:
            continue

        entries = lines.findall("line")
        files.append(
            (
                name,
                len(entries),
                sum(1 for line in entries if line.get("hits") != "0"),
            )
        )

    return files


def _percent(statements: int, covered: int) -> float:
    return round(covered / statements * 100, 2) if statements else 0.0


def measure_coverage() -> dict:
    files = _coverage_by_file()

    modules = {}

    for label, prefixes in CRITICAL_MODULES.items():
        selected = [f for f in files if any(f[0].startswith(p) for p in prefixes)]
        statements = sum(f[1] for f in selected)
        covered = sum(f[2] for f in selected)

        modules[label] = {
            "statements": statements,
            "covered": covered,
            "percent": _percent(statements, covered),
        }

    statements = sum(f[1] for f in files)
    covered = sum(f[2] for f in files)

    return {
        "total": {
            "statements": statements,
            "covered": covered,
            "percent": _percent(statements, covered),
        },
        "modules": modules,
    }


def measure_lint() -> dict:
    """Violation counts per rule, for the advisory ruleset.

    Counts, not pass/fail: the number going down over weeks is what shows
    a ratchet is working, and it tells you which rule to promote next.
    """

    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            "--select", "ALL",
            "--output-format", "json",
            "src",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    try:
        findings = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {"total": None, "by_rule": {}, "error": "ruff output unparseable"}

    by_rule: dict[str, int] = {}

    for finding in findings:
        code = finding.get("code") or "unknown"
        by_rule[code] = by_rule.get(code, 0) + 1

    return {
        "total": len(findings),
        "by_rule": dict(
            sorted(by_rule.items(), key=lambda kv: kv[1], reverse=True)[:15]
        ),
    }


def build_report() -> dict:
    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "coverage": measure_coverage(),
        "lint": measure_lint(),
    }


def render(report: dict) -> None:
    coverage = report["coverage"]

    print(f"Coverage  {coverage['total']['percent']:.1f}%  "
          f"({coverage['total']['covered']}/{coverage['total']['statements']} statements)")
    print()
    print(f"  {'module':22s} {'stmts':>7s} {'cov':>8s}")

    for label, data in coverage["modules"].items():
        if not data["statements"]:
            continue

        print(f"  {label:22s} {data['statements']:7d} {data['percent']:7.1f}%")

    lint = report["lint"]

    print()
    print(f"Lint      {lint['total']} advisory findings (top rules)")

    for code, count in list(lint["by_rule"].items())[:8]:
        print(f"  {code:10s} {count:5d}")


def record(report: dict) -> None:
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "measured_at": report["measured_at"],
            "coverage": report["coverage"]["total"]["percent"],
            "lint_findings": report["lint"]["total"],
        }) + "\n")


def check_floor(report: dict) -> bool:
    """Compare against a recorded floor, if one has been set."""

    if not FLOOR_FILE.exists():
        print(
            "\nNo coverage floor recorded yet. Collect a week of runs, then "
            "write .coverage-floor.json with a value slightly BELOW the "
            "observed minimum — a floor above where you actually sit blocks "
            "every PR on day one."
        )
        return True

    floor = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    actual = report["coverage"]["total"]["percent"]
    minimum = floor.get("total", 0)

    if actual + 1e-9 < minimum:
        print(f"\nFAIL coverage {actual:.2f}% is below the floor {minimum:.2f}%")
        return False

    print(f"\nOK   coverage {actual:.2f}% meets the floor {minimum:.2f}%")

    for label, required in (floor.get("modules") or {}).items():
        got = report["coverage"]["modules"].get(label, {}).get("percent", 0)

        if got + 1e-9 < required:
            print(f"FAIL {label} {got:.2f}% is below {required:.2f}%")
            return False

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Write the report here.")
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if below the recorded floor.")
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()

    report = build_report()
    render(report)

    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.no_history:
        record(report)

    sys.exit(0 if (not args.check or check_floor(report)) else 1)
