"""Turning a connection string into something asyncpg will accept.

Render supplies a database as five discrete fields. Neon — and the
Vercel integration that provisions it — supplies one URL, in libpq
form:

    postgresql://user:pw@ep-x-pooler.eu-central-1.aws.neon.tech/db
        ?sslmode=require&channel_binding=require

Handing that to asyncpg does not work, and none of the reasons announce
themselves clearly:

**`sslmode` and `channel_binding` are libpq parameters.** asyncpg is not
built on libpq and rejects them outright as unexpected keyword
arguments. It has its own `ssl` argument instead. psycopg2 *is* built on
libpq and wants them kept — which is why the sync URL Alembic uses is
built separately here rather than by string-replacing the driver name.

**The `-pooler` endpoint is pgbouncer in transaction mode.** Prepared
statements do not survive it, because successive statements in one
session may land on different server connections. asyncpg prepares
everything by default, so this surfaces later as
`InvalidSQLStatementName` or a duplicate-name error under load, rather
than as a failure to connect. SQLAlchemy documents three mitigations and
all three are needed: disable its prepared statement cache, give each
statement a unique name, and stop holding a local pool in front of a
pooler that is already pooling.

Getting this wrong produces an application that connects, serves
requests, and then fails intermittently under concurrency — so it is
centralised here with tests rather than spread across session.py and
alembic/env.py.
"""

from typing import Any

from sqlalchemy.engine import URL, make_url

# Understood by libpq (psycopg2), rejected by asyncpg. `sslmode` is
# translated rather than dropped; the rest carry no asyncpg equivalent
# that matters for this deployment.
_LIBPQ_ONLY_PARAMS = frozenset(
    {
        "sslmode",
        "channel_binding",
        "gssencmode",
        "target_session_attrs",
        "options",
        "sslcert",
        "sslkey",
        "sslrootcert",
        "sslcrl",
        "connect_timeout",
        "client_encoding",
    }
)

# libpq sslmode values that mean "encrypt". asyncpg takes the same
# vocabulary through its own `ssl` argument.
_SSL_REQUIRED = frozenset({"require", "verify-ca", "verify-full"})

_ASYNC_DRIVER = "postgresql+asyncpg"
_SYNC_DRIVER = "postgresql+psycopg2"


def _normalise(url: URL) -> URL:
    """`postgres://` and `postgresql://` both mean PostgreSQL.

    Providers are inconsistent about which they hand out — Heroku's
    historical `postgres://` is still widely copied — and SQLAlchemy
    accepts neither as an async driver.
    """

    return url.set(drivername=_ASYNC_DRIVER)


def is_pooled(url: URL) -> bool:
    """Whether this endpoint is a transaction-mode connection pooler.

    Neon names its pooled endpoint `...-pooler.<region>...`, which is
    the only signal available from the connection string alone. A false
    negative here is the expensive direction — it leaves prepared
    statements enabled through pgbouncer — so the check is deliberately
    loose.
    """

    host = url.host or ""

    return "-pooler." in host or "pgbouncer" in host


def async_url(dsn: str) -> URL:
    """The URL to hand to `create_async_engine`."""

    url = _normalise(make_url(dsn))

    query = {
        key: value
        for key, value in url.query.items()
        if key not in _LIBPQ_ONLY_PARAMS
    }

    if is_pooled(url):
        # SQLAlchemy caches prepared statements per connection. Behind a
        # transaction-mode pooler the connection a statement was
        # prepared on is not the one it executes on.
        query["prepared_statement_cache_size"] = "0"

    return url.set(query=query)


def async_connect_args(dsn: str) -> dict[str, Any]:
    """asyncpg-specific arguments that cannot live in the URL."""

    url = make_url(dsn)
    connect_args: dict[str, Any] = {}

    sslmode = url.query.get("sslmode")

    if isinstance(sslmode, str) and sslmode in _SSL_REQUIRED:
        # Neon requires TLS. Passing the libpq name through asyncpg's
        # own `ssl` argument keeps the intent and drops the parameter it
        # cannot parse.
        connect_args["ssl"] = sslmode

    if is_pooled(url):
        from uuid import uuid4

        # asyncpg numbers prepared statements sequentially per
        # connection. Through pgbouncer two clients can be issued the
        # same number against the same server connection, and the second
        # fails with a duplicate name. A uuid cannot collide.
        connect_args["prepared_statement_name_func"] = (
            lambda: f"__asyncpg_{uuid4()}__"
        )

    return connect_args


def use_null_pool(dsn: str) -> bool:
    """Whether SQLAlchemy should keep no pool of its own.

    True behind a pooler, which is already pooling — a second pool in
    front of it holds connections open that pgbouncer could have given
    to someone else, and on serverless multiplies by the instance count.
    """

    return is_pooled(make_url(dsn))


def sync_url(dsn: str) -> str:
    """The URL for Alembic, which runs on psycopg2.

    libpq parameters are kept: psycopg2 understands `sslmode` natively,
    and Neon's direct endpoint refuses an unencrypted connection.
    Migrations also run once, on a direct connection, so none of the
    pooler mitigations apply.
    """

    return make_url(dsn).set(drivername=_SYNC_DRIVER).render_as_string(
        hide_password=False
    )


def from_parts(
    *,
    username: str,
    password: str,
    host: str,
    port: int,
    database: str,
) -> str:
    """A DSN from the five discrete settings, for deployments that
    supply them that way rather than as a URL."""

    return URL.create(
        drivername=_ASYNC_DRIVER,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)
