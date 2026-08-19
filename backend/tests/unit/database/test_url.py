"""Connection string translation.

Every case here is one that fails *quietly* if it is wrong — the app
starts, connects, serves traffic, and then breaks under concurrency or
refuses a parameter deep inside the driver. That is why the logic has
its own module and its own tests rather than living inline in
session.py.
"""

import pytest
from sqlalchemy.engine import make_url

from src.database.url import (
    async_connect_args,
    async_url,
    from_parts,
    is_pooled,
    sync_url,
    use_null_pool,
)

# The exact shape Neon hands out, pooled and direct.
NEON_POOLED = (
    "postgresql://alice:pw@ep-cool-dawn-123456-pooler.eu-central-1.aws"
    ".neon.tech/pacopilot?sslmode=require&channel_binding=require"
)
NEON_DIRECT = (
    "postgresql://alice:pw@ep-cool-dawn-123456.eu-central-1.aws"
    ".neon.tech/pacopilot?sslmode=require"
)


class TestDriver:

    def test_the_async_driver_is_asyncpg(self):
        assert async_url(NEON_DIRECT).drivername == "postgresql+asyncpg"

    def test_the_bare_postgres_scheme_is_accepted(self):
        """Providers hand out `postgres://` and `postgresql://`
        interchangeably, and SQLAlchemy accepts neither as async."""

        url = async_url("postgres://alice:pw@db.example.com/pacopilot")

        assert url.drivername == "postgresql+asyncpg"

    def test_credentials_and_database_survive(self):
        url = async_url(NEON_POOLED)

        assert url.username == "alice"
        assert url.password == "pw"
        assert url.database == "pacopilot"
        assert url.host.endswith(".neon.tech")


class TestLibpqParameters:

    def test_sslmode_is_removed_from_the_async_url(self):
        """asyncpg is not built on libpq and rejects it as an
        unexpected keyword argument."""

        assert "sslmode" not in async_url(NEON_DIRECT).query

    def test_channel_binding_is_removed(self):
        assert "channel_binding" not in async_url(NEON_POOLED).query

    def test_sslmode_is_translated_rather_than_dropped(self):
        """Neon refuses an unencrypted connection, so removing the
        parameter without carrying the intent across would swap one
        failure for another."""

        assert async_connect_args(NEON_DIRECT)["ssl"] == "require"

    @pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
    def test_stricter_modes_are_carried_across_too(self, mode):
        dsn = f"postgresql://a:b@db.example.com/x?sslmode={mode}"

        assert async_connect_args(dsn)["ssl"] == mode

    def test_no_ssl_argument_when_none_was_asked_for(self):
        """A local Postgres over a unix-ish network has no TLS, and
        asking for it would fail the connection."""

        assert "ssl" not in async_connect_args(
            "postgresql://a:b@localhost:5432/x"
        )

    def test_unknown_parameters_are_left_alone(self):
        """Only the known libpq set is stripped.

        `prepared_statement_cache_size` is a SQLAlchemy dialect
        parameter that has to survive, so a blanket clear-out would
        break the pooler handling below.
        """

        dsn = "postgresql://a:b@db.example.com/x?application_name=pa"
        url = async_url(dsn)

        assert url.query.get("application_name") == "pa"


class TestPooledEndpoint:

    def test_a_pooler_endpoint_is_recognised(self):
        assert is_pooled(make_url(NEON_POOLED)) is True

    def test_a_direct_endpoint_is_not(self):
        assert is_pooled(make_url(NEON_DIRECT)) is False

    def test_prepared_statement_caching_is_disabled_when_pooled(self):
        """Through a transaction-mode pooler, the connection a statement
        was prepared on is not the one it executes on."""

        assert async_url(NEON_POOLED).query["prepared_statement_cache_size"] == "0"

    def test_statement_names_are_made_unique_when_pooled(self):
        """asyncpg numbers prepared statements sequentially per
        connection. Through pgbouncer two clients can be handed the same
        number against one server connection, and the second fails —
        under load, not at startup.
        """

        name_func = async_connect_args(NEON_POOLED)["prepared_statement_name_func"]

        assert name_func() != name_func()

    def test_sqlalchemy_keeps_no_pool_of_its_own_when_pooled(self):
        assert use_null_pool(NEON_POOLED) is True

    def test_a_direct_connection_keeps_its_pool(self):
        """The pool is worth having when nothing else is pooling."""

        assert use_null_pool(NEON_DIRECT) is False

    def test_a_direct_connection_gets_no_pooler_workarounds(self):
        url = async_url(NEON_DIRECT)

        assert "prepared_statement_cache_size" not in url.query
        assert "prepared_statement_name_func" not in async_connect_args(NEON_DIRECT)


class TestSyncUrlForAlembic:

    def test_it_uses_psycopg2(self):
        assert sync_url(NEON_DIRECT).startswith("postgresql+psycopg2://")

    def test_sslmode_is_kept(self):
        """psycopg2 *is* built on libpq and wants the parameter that
        asyncpg rejects. This is why the two URLs are built separately
        rather than by replacing the driver name in one string.
        """

        assert "sslmode=require" in sync_url(NEON_DIRECT)

    def test_the_password_is_rendered_not_masked(self):
        """`render_as_string` hides the password by default, which would
        produce a URL that connects as `***`.
        """

        assert "pw" in sync_url(NEON_DIRECT)

    def test_migrations_do_not_get_the_pooler_workarounds(self):
        """They run once, on one connection, and DDL through a
        transaction pooler is its own problem — the direct endpoint is
        the right target."""

        assert "prepared_statement_cache_size" not in sync_url(NEON_POOLED)


class TestDiscreteFields:

    def test_the_five_field_form_still_works(self):
        """Render's shape, and the local development default."""

        dsn = from_parts(
            username="pa",
            password="secret",
            host="localhost",
            port=5432,
            database="enterprise_ai",
        )

        url = async_url(dsn)

        assert url.drivername == "postgresql+asyncpg"
        assert url.host == "localhost"
        assert url.port == 5432
        assert url.database == "enterprise_ai"

    def test_a_password_with_url_characters_survives(self):
        """Generated passwords contain @ : / # regularly, and a naive
        f-string DSN would split the URL at the wrong character.
        """

        dsn = from_parts(
            username="pa",
            password="p@ss:w/rd#1",
            host="localhost",
            port=5432,
            database="db",
        )

        assert async_url(dsn).password == "p@ss:w/rd#1"


class TestSettingsResolution:

    def test_the_url_setting_wins_over_the_discrete_fields(self, monkeypatch):
        """A platform that injects DATABASE_URL should not also have to
        be told to unset the other five."""

        from src.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", NEON_DIRECT)

        assert settings.DATABASE_DSN == NEON_DIRECT

    def test_a_missing_configuration_names_what_is_missing(self, monkeypatch):
        """At startup, with the list — rather than at the first query
        with the string "None" inside the URL."""

        from src.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", None)
        monkeypatch.setattr(settings, "DATABASE_HOST", None)

        with pytest.raises(ValueError) as exc_info:
            _ = settings.DATABASE_DSN

        assert "DATABASE_HOST" in str(exc_info.value)
