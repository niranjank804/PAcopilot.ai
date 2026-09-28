"""Local only: a Super Admin with a password you know.

For running PA-Copilot on your own PC against a TM1 server on the same
network (see scripts/run-local.ps1). The hosted admin signs in with Google,
which does not accept localhost, so the local copy gets its own account.

Refuses any database that is not on this machine: it sets a password, and
must never be pointed at production.

    python scripts/local_admin.py [password]
"""

import asyncio
import os
import secrets
import sys
from urllib.parse import urlparse

from sqlalchemy import select

from scripts.seed_admin import seed_admin
from src.database.models.user import User
from src.database.session import AsyncSessionLocal
from src.services.password_service import password_service

EMAIL = "admin@local.test"


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    host = urlparse(url).hostname
    if host not in ("localhost", "127.0.0.1"):
        print(f"REFUSED: DATABASE_URL points at {host!r}, not this machine.")
        sys.exit(1)

    password = sys.argv[1] if len(sys.argv) > 1 else secrets.token_urlsafe(9)

    os.environ["BOOTSTRAP_ADMIN_EMAIL"] = EMAIL
    await seed_admin()

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one()
        user.password_hash = password_service.hash_password(password)
        user.is_active = True
        user.registration_status = "approved"
        await db.commit()
        username = user.username

    print(f"\n  Local sign-in:  username {username}   password {password}\n")


if __name__ == "__main__":
    asyncio.run(main())
