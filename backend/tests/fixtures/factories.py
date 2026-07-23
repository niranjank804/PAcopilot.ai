import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.organization import Organization
from src.database.models.user import User
from src.database.models.user_role import UserRole
from src.repositories.organization_repository import organization_repository
from src.repositories.role_repository import role_repository
from src.repositories.user_repository import user_repository
from src.repositories.user_role_repository import user_role_repository
from src.services.jwt_service import jwt_service
from src.services.password_service import password_service

DEFAULT_PASSWORD = "Password123"


async def create_organization(
    db: AsyncSession,
    name: str | None = None,
) -> Organization:
    suffix = uuid.uuid4().hex[:8]

    return await organization_repository.create(
        db,
        Organization(
            name=name or f"Org {suffix}",
            code=f"org-{suffix}",
        ),
    )


async def create_user(
    db: AsyncSession,
    organization_id: uuid.UUID,
    password: str = DEFAULT_PASSWORD,
    is_active: bool = True,
) -> User:
    suffix = uuid.uuid4().hex[:8]

    return await user_repository.create(
        db,
        User(
            organization_id=organization_id,
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_service.hash_password(password),
            first_name="Test",
            last_name="User",
            is_active=is_active,
        ),
    )


async def grant_system_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    role_name: str,
) -> UserRole:
    role = await role_repository.get_system_role(db, role_name)

    if role is None:
        raise RuntimeError(
            f"System role '{role_name}' not seeded — run scripts/seed_roles.py "
            "and scripts/seed_permissions.py against the test database first."
        )

    return await user_role_repository.create(
        db,
        UserRole(user_id=user_id, role_id=role.id),
    )


async def create_org_admin(db: AsyncSession) -> tuple[Organization, User]:
    org = await create_organization(db)
    user = await create_user(db, org.id)

    await grant_system_role(db, user.id, "Organization Admin")

    return org, user


def auth_headers(user: User) -> dict:
    token = jwt_service.create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}
