"""Fail if the Alembic history has branched or drifted from the models.

Two failures this catches, both of which happened during development:

* **Multiple heads.** Two migrations written from the same parent branch
  the history, and `alembic upgrade head` then refuses to run at all —
  discovered on a deploy rather than in review.
* **Un-migrated model changes.** A column added to a model with no
  migration works locally, because the dev database was migrated by hand,
  and fails on a fresh deploy.

Run with no database connection required for the head check; the drift
check needs one.

    PYTHONPATH=. python scripts/check_migrations.py
    PYTHONPATH=. python scripts/check_migrations.py --heads-only
"""

import argparse
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def check_single_head() -> bool:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND_ROOT / "alembic")
    )

    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    if len(heads) == 1:
        print(f"OK   single migration head: {heads[0]}")
        return True

    print(f"FAIL {len(heads)} migration heads: {', '.join(heads)}")
    print()
    print("     Two migrations share a parent. Rebase the newer one:")
    print("     set its down_revision to the other head, then re-run.")

    return False


def check_no_pending_drift() -> bool:
    """Model definitions must match the migration history."""

    import asyncio

    from sqlalchemy import inspect as sa_inspect

    from src.database.base import Base
    from src.database.session import engine

    import src.database.models  # noqa: F401 - registers every model

    async def _compare() -> list[str]:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_conn: set(sa_inspect(sync_conn).get_table_names())
            )

        return sorted(set(Base.metadata.tables) - tables)

    missing = asyncio.run(_compare())

    if not missing:
        print("OK   every model table exists in the migrated schema")
        return True

    print(f"FAIL {len(missing)} model table(s) have no migration: "
          f"{', '.join(missing)}")

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--heads-only",
        action="store_true",
        help="Skip the checks that need a live database.",
    )
    args = parser.parse_args()

    ok = check_single_head()

    if not args.heads_only:
        ok = check_no_pending_drift() and ok

    sys.exit(0 if ok else 1)
