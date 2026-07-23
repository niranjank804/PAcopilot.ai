import httpx2
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import engine, get_db
from src.main import app


@pytest_asyncio.fixture
async def db_session():
    connection = await engine.connect()
    transaction = await connection.begin()

    session = AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db

    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as async_client:
        yield async_client

    app.dependency_overrides.pop(get_db, None)
