"""Gateways: create, list, rotate, delete, and recognise one by its key."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    AuthenticationException,
    NotFoundException,
    ValidationException,
)
from src.database.models.tm1_connection import TM1Connection
from src.database.models.tm1_gateway import TM1Gateway
from src.reports.worker_credentials import hash_secret, verify_secret

KEY_PREFIX = "pagw_"

# A gateway polls about every 50 seconds; two missed polls is offline.
ONLINE_WITHIN = timedelta(seconds=120)

# Stamp last_seen at most this often, not on every poll.
_SEEN_EVERY = timedelta(seconds=20)


def _new_key(gateway_id: uuid.UUID, version: int) -> str:
    # The id and version travel in the key so it is found without a
    # hash-indexed lookup; the random part is what proves it.
    return f"{KEY_PREFIX}{gateway_id.hex}.{version}.{secrets.token_urlsafe(32)}"


def is_online(gateway: TM1Gateway, now: datetime | None = None) -> bool:
    if gateway.last_seen_at is None:
        return False
    return (now or datetime.now(UTC)) - gateway.last_seen_at <= ONLINE_WITHIN


class TM1GatewayService:

    async def create(
        self, db: AsyncSession, *, organization_id: uuid.UUID, created_by: uuid.UUID, name: str
    ) -> tuple[TM1Gateway, str]:
        gateway = TM1Gateway(
            id=uuid.uuid4(),
            organization_id=organization_id,
            created_by=created_by,
            name=name.strip(),
            key_version=1,
            key_hash="",
        )
        key = _new_key(gateway.id, 1)
        gateway.key_hash = hash_secret(key)
        db.add(gateway)
        await db.flush()
        return gateway, key

    async def list(self, db: AsyncSession, organization_id: uuid.UUID) -> list[TM1Gateway]:
        result = await db.execute(
            select(TM1Gateway)
            .where(TM1Gateway.organization_id == organization_id)
            .order_by(TM1Gateway.created_at)
        )
        return list(result.scalars().all())

    async def get(
        self, db: AsyncSession, gateway_id: uuid.UUID, organization_id: uuid.UUID
    ) -> TM1Gateway:
        gateway = await db.get(TM1Gateway, gateway_id)
        if gateway is None or gateway.organization_id != organization_id:
            raise NotFoundException("Gateway not found.")
        return gateway

    async def rotate_key(
        self, db: AsyncSession, gateway_id: uuid.UUID, organization_id: uuid.UUID
    ) -> tuple[TM1Gateway, str]:
        gateway = await self.get(db, gateway_id, organization_id)
        gateway.key_version += 1
        key = _new_key(gateway.id, gateway.key_version)
        gateway.key_hash = hash_secret(key)
        await db.flush()
        return gateway, key

    async def delete(
        self, db: AsyncSession, gateway_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        gateway = await self.get(db, gateway_id, organization_id)
        in_use = await db.scalar(
            select(func.count())
            .select_from(TM1Connection)
            .where(TM1Connection.gateway_id == gateway.id)
        )
        if in_use:
            raise ValidationException(
                f"{in_use} TM1 connection(s) use this gateway. Move or delete "
                "them first."
            )
        await db.delete(gateway)
        await db.flush()

    async def authenticate(self, db: AsyncSession, key: str) -> TM1Gateway:
        """The gateway presenting `key`, or AuthenticationException."""

        refused = AuthenticationException("Gateway key not recognised.")
        if not key.startswith(KEY_PREFIX):
            raise refused
        try:
            raw_id, raw_version, _ = key[len(KEY_PREFIX):].split(".", 2)
            gateway_id = uuid.UUID(hex=raw_id)
            version = int(raw_version)
        except ValueError:
            raise refused from None

        gateway = await db.get(TM1Gateway, gateway_id)
        if (
            gateway is None
            or gateway.key_version != version
            or not verify_secret(key, gateway.key_hash)
        ):
            raise refused
        return gateway

    async def mark_seen(
        self,
        db: AsyncSession,
        gateway: TM1Gateway,
        *,
        version: str | None,
        hostname: str | None,
    ) -> None:
        now = datetime.now(UTC)
        if gateway.last_seen_at and now - gateway.last_seen_at < _SEEN_EVERY:
            return
        gateway.last_seen_at = now
        gateway.version = (version or "")[:40] or None
        gateway.hostname = (hostname or "")[:255] or None
        await db.flush()


tm1_gateway_service = TM1GatewayService()
