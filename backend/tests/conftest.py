"""Suite-wide fixtures.

The test database is chosen here, before anything under ``src`` is
imported, because ``src.database.session`` builds the engine from settings
at import time. Everything below the first ``src`` import inherits it.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# ----------------------------------------------------------------------
# Test database
# ----------------------------------------------------------------------
# The suite never runs against the application's configured database.
# `backend/.env` is the *runtime* configuration, and on a developer machine
# it points wherever that developer last deployed — which, for a while,
# was production. Every test wraps itself in a transaction that is rolled
# back, but "every test rolls back" is a property of the tests written so
# far, not a guarantee: one fixture that commits, or a debugger left open
# mid-test, writes to whatever `.env` names.
#
# Resolution order:
#   1. TEST_DATABASE_URL in the environment (CI sets this).
#   2. TEST_DATABASE_URL in backend/.env.test (gitignored, per machine).
#   3. The docker-compose default from the repository root.
#
# Whichever wins must name a local host. A remote host is refused outright
# unless TEST_DATABASE_ALLOW_REMOTE=1 is set, which exists for a
# purpose-built remote test database and nothing else.

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_TEST_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/enterprise_ai_test"
)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _dotenv_value(path: Path, key: str) -> str | None:
    """One key from a dotenv file, without loading the file into the
    environment: only this key is wanted, and only here."""

    if not path.is_file():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, _, value = line.partition("=")

        if name.strip() == key:
            return value.strip().strip("'\"")

    return None


def _describe(url: str) -> str:
    """host:port/database — never the credentials."""

    parts = urlsplit(url)
    port = f":{parts.port}" if parts.port else ""

    return f"{parts.hostname or '?'}{port}{parts.path}"


def _select_test_database() -> str:
    url = (
        os.environ.get("TEST_DATABASE_URL")
        or _dotenv_value(_BACKEND_DIR / ".env.test", "TEST_DATABASE_URL")
        or _DEFAULT_TEST_DATABASE_URL
    )
    host = urlsplit(url).hostname or ""
    allow_remote = os.environ.get("TEST_DATABASE_ALLOW_REMOTE") == "1"

    if host not in _LOCAL_HOSTS and not allow_remote:
        raise pytest.UsageError(
            "Refusing to run the test suite against a remote database "
            f"({_describe(url)}). Tests run only against a local Postgres: "
            "start one with `docker compose up -d` and prepare it with "
            "`make test-db`, or point TEST_DATABASE_URL at a local server."
        )

    # Settings read the environment before .env, so this is what the
    # application under test connects to, whatever .env says.
    os.environ["DATABASE_URL"] = url
    os.environ.pop("DATABASE_URL_UNPOOLED", None)

    return url


TEST_DATABASE_URL = _select_test_database()

import httpx2  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.core import rate_limit  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.reports import storage as report_storage  # noqa: E402
from src.knowledge.embeddings import cache as embedding_cache  # noqa: E402
from src.database.session import engine, get_db  # noqa: E402
from src.main import app  # noqa: E402


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


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _test_database_reachable():
    """One clear message when the test database is down, instead of every
    test failing with the same connection traceback."""

    try:
        connection = await engine.connect()
    except Exception as exc:
        pytest.exit(
            f"The test database at {_describe(TEST_DATABASE_URL)} is not "
            f"reachable ({type(exc).__name__}: {exc}). Start it with "
            "`docker compose up -d` and prepare it with `make test-db`.",
            returncode=4,
        )

    await connection.close()


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
