from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import settings
from src.database.tenancy import register_tenant_listener


DATABASE_URL = settings.DATABASE_URL


engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
    # Verifies a pooled connection is still alive before handing it out,
    # so a connection the database closed underneath us costs one retry
    # rather than one failed request.
    pool_pre_ping=True,
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

register_tenant_listener()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise