"""Parse a folder of exported TI processes and print what was learned.

    python -m src.tm1.ti <folder> [--json <output-folder>]

Reads every `.pro` / `.txt` export in the folder, prints the standards report,
and optionally writes the structured JSON. Nothing is written to the database
and no network call is made, so this is safe to run against a production
export on a laptop.
"""

import argparse
import json
import sys
from pathlib import Path

from src.tm1.ti.conventions import infer_conventions
from src.tm1.ti.parser import parse_process
from src.tm1.ti.patterns import classify
from src.tm1.ti.report import build_report, render_markdown

# Credentials live in the export but must never reach an artifact on disk.
_HEAVY = ("prolog", "metadata", "data", "epilog", "datasource_query")


def _load(folder: Path):
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".pro", ".txt"))
    records, failed = [], []

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            records.append(parse_process(text, source_file=path.name))
        except Exception as exc:  # noqa: BLE001 - report, do not abort the batch
            failed.append((path.name, str(exc)))

    return records, failed


def _as_artifact(record) -> dict:
    payload = record.as_dict()

    # Source code stays out of the shared artifact: it is customer logic and
    # can embed connection strings. Structure is what the learning layer needs.
    for key in _HEAVY:
        payload[f"{key}_lines"] = len(payload[key].split("\n")) if payload[key] else 0
        del payload[key]

    payload["patterns"] = [
        {"key": m.key, "name": m.name, "score": m.score, "evidence": m.evidence}
        for m in classify(record)
    ]
    payload["comments"] = payload["comments"][:3]
    payload["header_comment"] = payload["header_comment"][:400]

    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.tm1.ti")
    parser.add_argument("folder", type=Path, help="folder of exported TI processes")
    parser.add_argument(
        "--json", type=Path, default=None, help="also write structured JSON here"
    )
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}", file=sys.stderr)
        return 2

    records, failed = _load(args.folder)

    if not records:
        print(f"No .pro or .txt exports found in {args.folder}", file=sys.stderr)
        return 1

    print(render_markdown(build_report(records)))

    if failed:
        print(f"\n{len(failed)} file(s) could not be parsed:")
        for name, error in failed:
            print(f"  - {name}: {error}")

    unknown = sorted({f for r in records for f in r.unknown_functions})
    if unknown:
        print(
            "\nFunctions not found in the reference library (verify these):\n  "
            + ", ".join(unknown)
        )

    if args.json:
        args.json.mkdir(parents=True, exist_ok=True)
        (args.json / "processes.json").write_text(
            json.dumps(
                {
                    "process_count": len(records),
                    "processes": [_as_artifact(r) for r in records],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (args.json / "coding_dna.json").write_text(
            json.dumps(infer_conventions(records).as_dict(), indent=2), encoding="utf-8"
        )
        print(f"\nWrote processes.json and coding_dna.json to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
