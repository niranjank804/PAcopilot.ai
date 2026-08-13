"""Where workbook and artifact bytes actually live.

Two backends, chosen by configuration:

* `S3StorageBackend` (src/reports/s3_storage.py) when `S3_BUCKET` is set.
  The right answer for a real deployment — Postgres is not an object
  store and a free-tier database is a hard ceiling.
* `DatabaseStorageBackend` otherwise. Correct for local development, and
  the only option before a bucket existed: a Render web service has an
  ephemeral filesystem, so local disk would lose every artifact on the
  next deploy and would not be visible to a second gunicorn worker.

The interface is what made that a swap rather than a rewrite. A
reference carries its own scheme (`db://<uuid>` or `s3://<bucket>/<key>`),
so artifacts written to Postgres before a bucket existed keep resolving
afterwards — switching backends does not orphan existing rows.

Two invariants every backend must keep:

* A reference is never handed to a client. Clients get an API path that
  re-checks permissions and tenancy on each call; the reference is an
  internal locator, and treating it as a capability URL is exactly the
  "artifact URL reuse" attack.
* Reads are organization-scoped. Passing a reference from another tenant
  must miss, not succeed — the check does not live only in the caller.
"""

import uuid
from abc import ABC, abstractmethod

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException
from src.database.models.report_blob import ReportBlob

_DB_SCHEME = "db://"


class StorageBackend(ABC):

    @abstractmethod
    async def put(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        data: bytes,
        content_type: str,
    ) -> str:
        """Store bytes, returning an opaque internal reference."""

    @abstractmethod
    async def get(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> bytes:
        """Fetch bytes. Raises NotFoundException across tenants."""

    @abstractmethod
    async def delete(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> None:
        """Remove bytes. Idempotent — deleting twice is not an error."""


class DatabaseStorageBackend(StorageBackend):
    """Postgres-backed blobs, sized for the POC.

    Deliberately capped by the caller (see settings.REPORT_MAX_* limits)
    rather than unbounded: bytea rows are read whole into memory by
    asyncpg, so this backend is appropriate for the tens-of-megabytes
    range a PAfE workbook occupies and not for arbitrary payloads.
    """

    async def put(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        data: bytes,
        content_type: str,
    ) -> str:
        blob = ReportBlob(
            organization_id=organization_id,
            content=data,
            size_bytes=len(data),
            content_type=content_type,
        )

        db.add(blob)

        await db.flush()

        return f"{_DB_SCHEME}{blob.id}"

    async def _load(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> ReportBlob | None:
        blob_id = self._parse(reference)

        if blob_id is None:
            return None

        result = await db.execute(
            select(ReportBlob).where(
                ReportBlob.id == blob_id,
                # Belt and braces alongside the session-level tenancy
                # filter, which is still behind a feature flag.
                ReportBlob.organization_id == organization_id,
            )
        )

        return result.scalar_one_or_none()

    async def get(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> bytes:
        blob = await self._load(
            db,
            organization_id=organization_id,
            reference=reference,
        )

        if blob is None:
            raise NotFoundException("The stored file could not be found.")

        return bytes(blob.content)

    async def delete(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> None:
        blob_id = self._parse(reference)

        if blob_id is None:
            return

        await db.execute(
            delete(ReportBlob).where(
                ReportBlob.id == blob_id,
                ReportBlob.organization_id == organization_id,
            )
        )

    @staticmethod
    def _parse(reference: str) -> uuid.UUID | None:
        if not reference.startswith(_DB_SCHEME):
            return None

        try:
            return uuid.UUID(reference[len(_DB_SCHEME) :])
        except ValueError:
            return None


def _select_backend() -> StorageBackend:
    """S3 when a bucket is configured, Postgres otherwise.

    Resolved once, lazily, on first use — not at import — so tests and
    scripts can set S3_BUCKET before anything touches storage, and so an
    unconfigured deployment never constructs an S3 client or attempts
    credential resolution.

    Existing rows keep working across the switch: a reference carries its
    own scheme (`db://` or `s3://`), so artifacts written to Postgres
    before a bucket existed still resolve afterwards.
    """

    from src.core.config import settings

    if settings.S3_BUCKET:
        from src.reports.s3_storage import S3StorageBackend

        return S3StorageBackend()

    return DatabaseStorageBackend()


_backend: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    global _backend

    if _backend is None:
        _backend = _select_backend()

    return _backend


def reset_storage_backend() -> None:
    """Force re-selection. For tests that change S3_BUCKET."""

    global _backend

    _backend = None
