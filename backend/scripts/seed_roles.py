import asyncio

from src.database.models.role import Role
from src.database.session import AsyncSessionLocal
from src.repositories.role_repository import role_repository

SYSTEM_ROLES = [
    ("Super Admin", "Full access across all organizations."),
    ("Organization Admin", "Full access within a single organization."),
    ("Planner", "Can create and manage plans."),
    ("Analyst", "Can view and analyze data."),
    ("Viewer", "Read-only access."),
]


async def seed_roles() -> None:
    async with AsyncSessionLocal() as db:
        for name, description in SYSTEM_ROLES:
            existing = await role_repository.get_system_role(
                db,
                name,
            )

            if existing:
                print(f"Skipping existing role: {name}")
                continue

            role = Role(
                organization_id=None,
                name=name,
                description=description,
                is_system=True,
            )

            await role_repository.create(
                db,
                role,
            )

            print(f"Created role: {name}")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_roles())
