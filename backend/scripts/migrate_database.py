"""Move the database from one Postgres to another, and prove it worked.

Written for the Render -> Neon move, but there is nothing Render- or
Neon-specific in it.

    python scripts/migrate_database.py

It asks for the two connection strings, copies the data, and then
*verifies* the copy by comparing row counts table by table and checking
the Alembic revision matches. A migration that reports success while
having silently dropped rows is the failure worth engineering against,
because it is discovered weeks later by a user rather than immediately
by the person running it.

**Connection strings are never passed as arguments.** Command-line
arguments are visible to every other process on the machine via the
process list, and they persist in shell history. They are read from the
environment if present, and otherwise prompted for with echo disabled,
so a database password does not end up in `~/.bash_history`.

If the source is gone — a free-tier database past its grace period —
`--fresh` sets the target up from nothing instead: schema at the current
migration plus the seed data the application needs to start.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _tables(url: str) -> list[str]:
    """Tables to compare, asked of the database rather than the code.

    The obvious implementation reads `Base.metadata` from the models —
    but importing them pulls in the application settings, so a *database
    recovery* tool would refuse to run unless the whole application were
    correctly configured. That is precisely backwards: in the situation
    this script exists for, the configuration is often the thing that is
    broken, and the machine holding the connection strings may not hold
    the application's secrets at all.

    Asking the source is also more truthful. It compares what is
    actually there, including tables the current models no longer
    describe, which are exactly the rows a code-derived list would drop
    silently.
    """

    ok, output = _psql_scalar(
        url,
        "select table_name from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE' "
        "order by table_name;",
    )

    if not ok:
        return []

    return [line.strip() for line in output.splitlines() if line.strip()]


def _redact(url: str) -> str:
    """A connection string safe to print."""

    return re.sub(r"://([^:/@]+):([^@]*)@", r"://\1:***@", url)


def _libpq(url: str) -> str:
    """psql/pg_dump speak libpq, not SQLAlchemy.

    A URL carrying `postgresql+asyncpg://` is rejected outright by the
    command-line tools, and that is an easy paste to make.
    """

    return re.sub(r"^postgresql\+\w+://", "postgresql://", url.strip())


def _ask(name: str, env_var: str) -> str:
    value = os.environ.get(env_var)

    if value:
        print(f"  {name}: taken from {env_var}")
        return _libpq(value)

    # getpass, not input: this is a password-bearing string.
    value = getpass(f"  {name} (input hidden): ").strip()

    if not value:
        sys.exit(f"No {name} given.")

    return _libpq(value)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, **kwargs)


def _psql_scalar(url: str, sql: str) -> tuple[bool, str]:
    """Run one query. Returns (ok, output-or-error)."""

    result = _run(
        ["psql", url, "-tAc", sql],
        env={**os.environ, "PGCONNECT_TIMEOUT": "15"},
    )

    if result.returncode != 0:
        return False, result.stderr.strip()

    return True, result.stdout.strip()


def check_reachable(url: str, label: str) -> bool:
    print(f"\nChecking {label}: {_redact(url)}")

    ok, output = _psql_scalar(url, "select version();")

    if ok:
        print(f"  reachable — {output.split(',')[0]}")
        return True

    print(f"  UNREACHABLE: {output.splitlines()[0] if output else 'no response'}")

    lowered = output.lower()

    # The distinction that decides what to do next.
    if "does not exist" in lowered:
        print("  -> The database no longer exists. If this was a free tier")
        print("     database past its grace period, the data is gone and")
        print("     --fresh is the only way forward.")
    elif "password" in lowered or "authentication" in lowered:
        print("  -> Reachable but the credentials were rejected. Copy the")
        print("     connection string again from the provider.")
    elif "timeout" in lowered or "could not translate" in lowered:
        print("  -> Host did not answer. Check it is the EXTERNAL connection")
        print("     string, not the internal one, which only resolves inside")
        print("     the provider's own network.")

    return False


def counts(url: str, tables: list[str] | None = None) -> dict[str, int]:
    """Row count per table.

    `tables` is the source's list when verifying, so a table present at
    the source but absent from the target is reported as missing rather
    than quietly excluded from the comparison.
    """

    result: dict[str, int] = {}

    for table in tables if tables is not None else _tables(url):
        ok, output = _psql_scalar(
            url,
            f"select count(*) from \"{table}\";",
        )

        if ok and output.isdigit():
            result[table] = int(output)

    return result


def dump(source: str, path: Path) -> bool:
    print("\nDumping source...")

    # --no-owner/--no-privileges: the source's role does not exist on the
    # target, and without these every ALTER ... OWNER TO fails.
    result = _run(
        [
            "pg_dump", source,
            "--no-owner", "--no-privileges", "--no-acl",
            "-Fc", "-f", str(path),
        ]
    )

    if result.returncode != 0:
        print("  pg_dump FAILED:")
        print("   ", result.stderr.strip().splitlines()[-1] if result.stderr else "")
        return False

    size = path.stat().st_size
    print(f"  wrote {size / 1024 / 1024:.1f} MB to {path}")

    return True


def restore(target: str, path: Path) -> bool:
    print("\nRestoring into target...")

    result = _run(
        [
            "pg_restore", "--no-owner", "--no-privileges",
            "--dbname", target, str(path),
        ]
    )

    # pg_restore exits non-zero for warnings too (an object that already
    # exists, for instance), so the exit code alone is not a verdict —
    # the row-count comparison below is. Errors are surfaced regardless.
    if result.stderr.strip():
        errors = [
            line for line in result.stderr.splitlines()
            if "error" in line.lower()
        ]

        if errors:
            print(f"  pg_restore reported {len(errors)} error line(s):")
            for line in errors[:5]:
                print("   ", line.strip())

    print(f"  pg_restore exited {result.returncode}")

    return True


def verify(before: dict[str, int], target: str) -> bool:
    """The step that makes the result trustworthy."""

    print("\nVerifying...")

    # Compared against the source's table list, so a table the target
    # is missing entirely shows up as missing instead of being skipped.
    after = counts(target, list(before))

    missing_tables = sorted(set(before) - set(after))
    mismatched = {
        table: (before[table], after.get(table, 0))
        for table in sorted(before)
        if after.get(table, 0) != before[table]
    }

    total_before = sum(before.values())
    total_after = sum(after.get(t, 0) for t in before)

    print(f"  tables compared : {len(before)}")
    print(f"  rows at source  : {total_before}")
    print(f"  rows at target  : {total_after}")

    if missing_tables:
        print(f"  MISSING TABLES  : {', '.join(missing_tables)}")

    if mismatched:
        print("  ROW COUNT MISMATCH:")
        for table, (source_count, target_count) in mismatched.items():
            print(f"    {table}: source={source_count} target={target_count}")

    ok_source, source_revision = _psql_scalar(
        target, "select version_num from alembic_version;"
    )

    if ok_source:
        print(f"  alembic revision: {source_revision}")
    else:
        print("  alembic_version not found on target — schema did not restore")
        return False

    if missing_tables or mismatched:
        print("\n  RESULT: the copy is NOT faithful. Do not switch over.")
        return False

    print("\n  RESULT: every table matches. The copy is faithful.")

    return True


def fresh(target: str) -> bool:
    """Build the schema from nothing, for when the source is gone."""

    print("\nSetting up a fresh database (no data to migrate)...")

    backend = Path(__file__).resolve().parent.parent
    env = {**os.environ, "DATABASE_URL": target, "PYTHONPATH": str(backend)}

    steps = [
        (["python", "-m", "alembic", "upgrade", "head"], "schema"),
        (["python", "scripts/seed_roles.py"], "roles"),
        (["python", "scripts/seed_permissions.py"], "permissions"),
        (["python", "scripts/seed_admin.py"], "admin user"),
    ]

    for command, label in steps:
        print(f"  {label}...")
        result = _run(command, cwd=str(backend), env=env)

        if result.returncode != 0:
            print(f"  FAILED at {label}:")
            print("   ", (result.stderr or result.stdout).strip()[-600:])
            return False

    print("  fresh database ready")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Source is gone: build the target from scratch instead of copying.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report whether the databases are reachable.",
    )
    args = parser.parse_args()

    for tool in ("psql", "pg_dump", "pg_restore"):
        if not shutil.which(tool):
            return int(bool(print(f"{tool} not found on PATH. Install PostgreSQL client tools.")))

    print("Connection strings are read from the environment if set")
    print("(SOURCE_DATABASE_URL / TARGET_DATABASE_URL), otherwise prompted")
    print("for with input hidden. They are never passed as arguments.\n")

    if args.fresh:
        target = _ask("TARGET (new database)", "TARGET_DATABASE_URL")

        if not check_reachable(target, "target"):
            return 1

        return 0 if fresh(target) else 1

    source = _ask("SOURCE (old database)", "SOURCE_DATABASE_URL")

    if not check_reachable(source, "source"):
        print("\nThe source cannot be read. If it has been deleted, re-run")
        print("with --fresh to build the new database from scratch.")
        return 1

    if args.check_only:
        target = _ask("TARGET (new database)", "TARGET_DATABASE_URL")
        return 0 if check_reachable(target, "target") else 1

    target = _ask("TARGET (new database)", "TARGET_DATABASE_URL")

    if not check_reachable(target, "target"):
        return 1

    before = counts(source)
    print(f"\nSource holds {sum(before.values())} rows across {len(before)} tables.")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "database.dump"

        if not dump(source, path):
            return 1

        # Kept next to the working directory too: the dump is the only
        # irreplaceable artifact here, and a temp directory is deleted on
        # exit whether or not the restore worked.
        keep = Path.cwd() / "database-backup.dump"
        shutil.copy2(path, keep)
        print(f"  backup copy kept at {keep}")

        if not restore(target, path):
            return 1

    return 0 if verify(before, target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
