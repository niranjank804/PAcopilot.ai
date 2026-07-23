import asyncio
import os
import secrets

from src.database.models.organization import Organization
from src.database.models.user import User
from src.database.models.user_role import UserRole
from src.database.session import AsyncSessionLocal
from src.repositories.organization_repository import organization_repository
from src.repositories.role_repository import role_repository
from src.repositories.user_repository import user_repository
from src.repositories.user_role_repository import user_role_repository
from src.services.password_service import password_service

DEFAULT_ORG_CODE = "default"
DEFAULT_ORG_NAME = "PA-Copilot"


async def seed_admin() -> None:
    # Self-registration (auth_service.register()) now auto-approves into a
    # default org on its own, so this is no longer strictly required to get
    # *a* way in - but it's still the only way to get the specific owner
    # email into the Super Admin role with a known org, rather than an
    # arbitrary self-registered account.
    # .strip().lower() defends against trailing whitespace/newlines from
    # pasting into a dashboard env var field, and against Google's email
    # claim being lowercase when the pasted value isn't - either would
    # silently break the exact-match lookup in google_login otherwise.
    email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()

    if not email:
        print("BOOTSTRAP_ADMIN_EMAIL not set, skipping admin bootstrap.")
        return

    async with AsyncSessionLocal() as db:
        existing = await user_repository.get_by_email(db, email)

        if existing:
            print(f"User already exists for {email}, skipping admin bootstrap.")
            return

        organization = await organization_repository.get_by_code(
            db,
            DEFAULT_ORG_CODE,
        )

        if organization is None:
            organization = await organization_repository.create(
                db,
                Organization(
                    name=DEFAULT_ORG_NAME,
                    code=DEFAULT_ORG_CODE,
                    is_active=True,
                ),
            )
            print(f"Created organization '{DEFAULT_ORG_NAME}' (code={DEFAULT_ORG_CODE})")

        super_admin_role = await role_repository.get_system_role(
            db,
            "Super Admin",
        )

        if super_admin_role is None:
            print("Super Admin role not found - run seed_roles.py first.")
            return

        username = email.split("@")[0]
        base_username = username
        suffix = 1

        while await user_repository.get_by_username(db, username):
            username = f"{base_username}{suffix}"
            suffix += 1

        user = await user_repository.create(
            db,
            User(
                organization_id=organization.id,
                username=username,
                email=email,
                # Not communicated anywhere - this account is meant to sign
                # in via Google Sign-In, or via "Forgot password" if a
                # password login is ever needed.
                password_hash=password_service.hash_password(
                    secrets.token_urlsafe(32)
                ),
                first_name="Admin",
                last_name="User",
                is_active=True,
                registration_status="approved",
            ),
        )

        await user_role_repository.create(
            db,
            UserRole(
                user_id=user.id,
                role_id=super_admin_role.id,
            ),
        )

        await db.commit()

        print(
            f"Created Super Admin user '{username}' ({email}) "
            f"in organization '{DEFAULT_ORG_CODE}'"
        )


if __name__ == "__main__":
    asyncio.run(seed_admin())
