from src.database.base import Base
import src.database.models
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.core.config import settings


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """
    Convert asyncpg URL to psycopg2 URL for Alembic.
    """
    return (
        settings.DATABASE_URL
        .render_as_string(hide_password=False)
        .replace(
            "postgresql+asyncpg",
            "postgresql+psycopg2"
        )
    )


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    context.configure(
        url=get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    connectable = create_engine(
        get_sync_url(),
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()