"""Check that a test suite fails when the code it covers is broken.

A test that passes whether or not the behaviour exists is worse than no
test: it reports green and suppresses doubt. This applies a small edit to
a source file, runs the suite, and expects it to FAIL.

Restore is via `git checkout --`, not an in-memory copy. A crash, a
timeout or a Ctrl-C partway through must never leave a mutation in the
working tree — which happened once with the in-memory approach.

    python scripts/mutate.py --config scripts/mutations/chat.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def uncommitted_changes(path: Path) -> bool:
    """True if the file differs from HEAD or is untracked.

    Mutating such a file is refused: the only safe restore is the copy
    taken below, and if that copy is ever lost there is no second chance,
    because git no longer holds the current content either.
    """

    result = subprocess.run(
        ["git", "status", "--porcelain", "--", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    )

    return bool(result.stdout.strip())


def run_suite(command: list[str], cwd: Path) -> bool:
    """True if the suite passed."""

    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", shell=True,
    )
    return result.returncode == 0


def apply_mutation(path: Path, find: str, replace: str) -> None:
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(find)

    if occurrences != 1:
        raise SystemExit(
            f"{path}: anchor matched {occurrences} times, expected exactly 1"
        )

    path.write_text(source.replace(find, replace), encoding="utf-8")


def main(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))

    cwd = ROOT / config.get("cwd", ".")
    command = config["command"]
    survivors = []

    for mutation in config["mutations"]:
        target = ROOT / mutation["file"]

        if uncommitted_changes(target):
            raise SystemExit(
                f"{target} has uncommitted changes. Commit or stash "
                "them first - a mutation run must never be the reason "
                "unsaved work disappears."
            )

        # Byte-for-byte snapshot, restored in `finally` on every path out,
        # including an unmatched anchor or Ctrl-C.
        original = target.read_bytes()

        try:
            apply_mutation(target, mutation["find"], mutation["replace"])
            passed = run_suite(command, cwd)
        finally:
            target.write_bytes(original)

        if passed:
            survivors.append(mutation["name"])
            print(f"SURVIVED  {mutation['name']}")
        else:
            print(f"caught    {mutation['name']}")

    print()

    if survivors:
        print(f"{len(survivors)} mutation(s) survived — the suite would not "
              "notice these regressions:")
        for name in survivors:
            print(f"  - {name}")
        return 1

    print(f"All {len(config['mutations'])} mutations caught.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    sys.exit(main(args.config))
