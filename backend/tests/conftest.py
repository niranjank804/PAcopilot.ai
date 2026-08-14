import httpx2
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import rate_limit
from src.core.config import settings
from src.reports import storage as report_storage
from src.knowledge.embeddings import cache as embedding_cache
from src.database.session import engine, get_db
from src.main import app


@pytest.fixture(autouse=True)
def _clean_embedding_cache():
    """Every test starts with an empty query-embedding cache.

    The cache is process-global by design — that is what makes it useful
    across requests — but it also means one test's cached query silently
    changes another's behaviour. A test asserting that a failing
    embedding provider surfaces an error will pass on its own and fail in
    the suite, because the cache short-circuits before the provider is
    ever called. Same reasoning as the rate-limit fixture below.
    """

    embedding_cache.clear()
    yield
    embedding_cache.clear()


@pytest.fixture(autouse=True)
def _pinned_storage_backend(request, monkeypatch):
    """Storage is Postgres in tests, whatever the environment says.

    The backend is chosen from `S3_BUCKET`, which is real configuration a
    developer may well have set in `.env`. Without this, the suite's
    behaviour depends on the machine it runs on: 28 report tests upload a
    workbook, and with a bucket configured they leave the fakes behind
    and talk to AWS.

    The failure mode with a *valid* key is the dangerous one, because it
    is not a failure — the tests pass, having written test objects into
    the real bucket on every run. An invalid key is what made this
    visible at all.

    Tests that genuinely want S3 opt in: `s3_configured` for the fake
    client, the `live_aws` marker for the real bucket.
    """

    if request.node.get_closest_marker("live_aws"):
        yield
        return

    monkeypatch.setattr(settings, "S3_BUCKET", None)
    report_storage.reset_storage_backend()

    yield

    report_storage.reset_storage_backend()


@pytest.fixture(autouse=True)
def _clean_rate_limit_windows():
    """Every test starts with an empty limiter.

    The limiter stays *enabled* so tests exercise the real path, but every
    request in the suite arrives from the same client address — without
    this, the sixth registration in the whole run would 429 and failures
    would depend on test ordering.
    """

    rate_limit.reset()
    yield
    rate_limit.reset()


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
