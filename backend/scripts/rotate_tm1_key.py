"""Re-encrypt stored connection credentials under a new Fernet key.

Step 2 of the rotation described in `src/tm1/crypto.py`:

1. Set `TM1_CREDENTIALS_KEY` to the new key and
   `TM1_CREDENTIALS_KEY_PREVIOUS` to the old one, and deploy.
2. Run this.
3. Remove `TM1_CREDENTIALS_KEY_PREVIOUS`.

Safe to interrupt and safe to re-run. Each row is rotated and committed
in its own transaction, so a crash leaves some rows on the new key and
some on the old — and both still decrypt, because both keys are
configured until step 3. Running it again is a no-op for rows already
on the new key.

Plaintext is never materialised: `MultiFernet.rotate` decrypts and
re-encrypts internally, so no password is ever held in a Python
variable here, printed, or logged.

    python scripts/rotate_tm1_key.py --dry-run   # count what would change
    python scripts/rotate_tm1_key.py
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.database.models.planning_analytics_connection import (  # noqa: E402
    PlanningAnalyticsConnection,
)
from src.database.models.tm1_connection import TM1Connection  # noqa: E402
from src.database.session import AsyncSessionLocal, engine  # noqa: E402
from src.tm1.crypto import rotate_token  # noqa: E402
from src.tm1.exceptions import TM1ConnectionError  # noqa: E402

# (model, ciphertext attribute). Both tables store Fernet tokens made by
# src/tm1/crypto.py; a third would have to be added here or its rows
# would silently keep the retired key.
TARGETS = [
    (TM1Connection, "encrypted_password"),
    (PlanningAnalyticsConnection, "encrypted_credential"),
]


async def rotate(dry_run: bool) -> int:
    rotated = 0
    failed = 0

    for model, column in TARGETS:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(select(model))
            identifiers = [row.id for row in rows.scalars().all()]

        print(f"{model.__tablename__}.{column}: {len(identifiers)} row(s)")

        for identifier in identifiers:
            # One transaction per row. A failure part-way through leaves
            # the remainder on the old key, which still decrypts.
            async with AsyncSessionLocal() as session:
                record = await session.get(model, identifier)

                if record is None:
                    continue

                token = getattr(record, column)

                if not token:
                    continue

                try:
                    new_token = rotate_token(token)
                except TM1ConnectionError as exc:
                    # Neither key decrypts it. Reported and skipped
                    # rather than aborting, so one unreadable legacy row
                    # cannot block the whole rotation.
                    print(f"  ! {identifier}: {exc}")
                    failed += 1
                    continue

                if not dry_run:
                    setattr(record, column, new_token)
                    await session.commit()

                rotated += 1

    verb = "would re-encrypt" if dry_run else "re-encrypted"
    print(f"\n{verb} {rotated} credential(s)")

    if failed:
        print(
            f"{failed} could not be decrypted by any configured key. "
            "Those connections need their credentials re-entered."
        )

    return failed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    if not settings.TM1_CREDENTIALS_KEY:
        print("TM1_CREDENTIALS_KEY is not set. Nothing to rotate to.")
        return 1

    if not settings.TM1_CREDENTIALS_KEY_PREVIOUS:
        # Not fatal: re-running after step 3, or rotating a single-key
        # deployment, is legitimate. But the usual reason to see this is
        # having forgotten step 1, in which case every row will fail to
        # decrypt and the message below is the explanation.
        print(
            "Note: TM1_CREDENTIALS_KEY_PREVIOUS is not set, so only rows "
            "already encrypted under the current key can be read.\n"
        )

    try:
        failed = await rotate(args.dry_run)
    finally:
        await engine.dispose()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
