"""Shared setup for tests/performance/benchmark_*.py — not a pytest module
(no test_* names), just a helper the standalone benchmark scripts import."""

import os

from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.session import AsyncSessionLocal
from src.repositories.organization_repository import organization_repository
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user


def require_env(name: str) -> str:
    value = os.environ.get(name)

    if not value:
        raise SystemExit(f"{name} is required — set it and re-run.")

    return value


def tm1_config_from_env() -> dict:
    return {
        "address": require_env("TM1_ADDRESS"),
        "port": int(os.environ.get("TM1_PORT", "8010")),
        "ssl": os.environ.get("TM1_SSL", "true").strip().lower() == "true",
        "username": require_env("TM1_USER"),
        "password": require_env("TM1_PASSWORD"),
    }


def ensure_credentials_key() -> None:
    if not settings.TM1_CREDENTIALS_KEY:
        settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
        crypto_module._fernet = None


async def create_benchmark_connection(db, config: dict, name: str):
    org = await create_organization(db)
    user = await create_user(db, org.id)

    connection = await tm1_integration_service.create_connection(
        db,
        organization_id=org.id,
        created_by=user.id,
        name=name,
        address=config["address"],
        port=config["port"],
        ssl=config["ssl"],
        username=config["username"],
        password=config["password"],
    )
    await db.commit()

    return org, user, connection


async def cleanup_benchmark_org(db, org) -> None:
    await organization_repository.delete(db, org)
    await db.commit()


__all__ = [
    "AsyncSessionLocal",
    "require_env",
    "tm1_config_from_env",
    "ensure_credentials_key",
    "create_benchmark_connection",
    "cleanup_benchmark_org",
]
