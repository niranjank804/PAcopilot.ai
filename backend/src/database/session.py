from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.database import url as database_url
from src.database.tenancy import register_tenant_listener


_DSN = settings.DATABASE_DSN

DATABASE_URL = database_url.async_url(_DSN)

# Behind a transaction-mode pooler (Neon's `-pooler` endpoint) SQLAlchemy
# keeps no pool of its own: pgbouncer is already pooling, and a second
# pool in front of it holds server connections that pgbouncer could have
# handed to someone else — multiplied by the instance count on
# serverless. See src/database/url.py for the rest of what that endpoint
# requires.
_pooled = database_url.use_null_pool(_DSN)

_pool_options = (
    {"poolclass": NullPool}
    if _pooled
    else {
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_timeout": settings.DATABASE_POOL_TIMEOUT_SECONDS,
        "pool_recycle": settings.DATABASE_POOL_RECYCLE_SECONDS,
        # Verifies a pooled connection is still alive before handing it
        # out, so a connection the database closed underneath us costs
        # one retry rather than one failed request.
        "pool_pre_ping": True,
    }
)


engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=database_url.async_connect_args(_DSN),
    **_pool_options,
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