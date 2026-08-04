"""Grant the default role to accounts that were created without one.

Self-registration used to create an approved, active user with no role at
all. Those accounts can log in and then fail every permission check —
"Missing permission: ai.chat" on the chat page, "knowledge.read" on the
knowledge base — so the product looks broken to exactly the people who
just signed up.

The registration path now assigns settings.DEFAULT_SIGNUP_ROLE, but that
does nothing for accounts already created. This grants the same role to
every user who currently holds no role at all.

Only touches users with ZERO roles. An account an administrator
deliberately left unprivileged is indistinguishable from one this bug
created, so the conservative reading is taken: anyone with any role
assigned is left completely alone.

Run with --dry-run first to see who would be affected.

    PYTHONPATH=. python scripts/backfill_default_role.py --dry-run
    PYTHONPATH=. python scripts/backfill_default_role.py
"""

import argparse
import asyncio

from sqlalchemy import select

from src.core.config import settings
from src.database.models.user import User
from src.database.models.user_role import UserRole
from src.database.session import AsyncSessionLocal
from src.repositories.role_repository import role_repository


async def backfill(dry_run: bool, exclude: set[str]) -> None:
    role_name = settings.DEFAULT_SIGNUP_ROLE.strip()

    if not role_name:
        print("DEFAULT_SIGNUP_ROLE is empty — nothing to grant.")
        return

    async with AsyncSessionLocal() as db:
        role = await role_repository.get_system_role(db, role_name)

        if role is None:
            print(
                f"System role {role_name!r} not found. "
                "Run scripts/seed_roles.py and scripts/seed_permissions.py "
                "first."
            )
            return

        result = await db.execute(
            select(User)
            .where(~select(UserRole.id)
                   .where(UserRole.user_id == User.id)
                   .exists())
            .order_by(User.created_at)
        )
        users = [
            user
            for user in result.scalars().all()
            if user.username not in exclude
        ]

        if not users:
            print("No users are missing a role.")
            return

        print(f"{len(users)} user(s) hold no role:\n")

        for user in users:
            print(f"  {user.username:24s} {user.email}")

        # seed_admin.py grants Super Admin, so an administrator appearing
        # here means seeding ran out of order — not that they should become
        # an Analyst. Granting the default would silently downgrade them and
        # the next run would skip them, because they would then have a role.
        suspected_admins = [
            user.username
            for user in users
            if "admin" in user.username.lower() or "admin" in user.email.lower()
        ]

        if suspected_admins:
            print(
                "\nWARNING: these look like administrator accounts: "
                f"{', '.join(suspected_admins)}\n"
                "Granting them the default role would leave them without "
                "admin rights. Re-run scripts/seed_admin.py for those "
                "instead, or pass --exclude "
                f"{','.join(suspected_admins)}"
            )

        if dry_run:
            print(f"\nDry run — would grant {role_name!r} to each.")
            return

        for user in users:
            db.add(UserRole(user_id=user.id, role_id=role.id))

        await db.commit()

        print(f"\nGranted {role_name!r} to {len(users)} user(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected users without changing anything.",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated usernames to leave untouched.",
    )
    args = parser.parse_args()

    excluded = {name.strip() for name in args.exclude.split(",") if name.strip()}

    asyncio.run(backfill(args.dry_run, excluded))
