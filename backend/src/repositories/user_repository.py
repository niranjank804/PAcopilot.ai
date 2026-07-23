from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.user import User


class UserRepository:

    async def get_by_username(
        self,
        db: AsyncSession,
        username: str,
    ) -> User | None:

        result = await db.execute(
            select(User).where(User.username == username)
        )

        return result.scalar_one_or_none()

    async def get_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> User | None:

        result = await db.execute(
            select(User).where(User.email == email)
        )

        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        db: AsyncSession,
        user_id,
    ) -> User | None:

        result = await db.execute(
            select(User).where(User.id == user_id)
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id,
        registration_status: str | None = None,
    ) -> list[User]:

        query = select(User).where(User.organization_id == organization_id)

        if registration_status is not None:
            query = query.where(User.registration_status == registration_status)

        result = await db.execute(query.order_by(User.created_at.desc()))

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        user: User,
    ) -> User:

        db.add(user)

        await db.flush()

        await db.refresh(user)

        return user

    async def update(
        self,
        db: AsyncSession,
        user: User,
    ) -> User:

        await db.flush()
        await db.refresh(user)

        return user

    async def delete(
        self,
        db: AsyncSession,
        user: User,
    ) -> None:

        await db.delete(user)
        await db.flush()


user_repository = UserRepository()