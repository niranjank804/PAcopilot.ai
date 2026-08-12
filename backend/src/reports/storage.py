"""Where workbook and artifact bytes actually live.

PA-Copilot has no object store today (no S3/GCS credentials, no bucket in
render.yaml), so the only correct place for binary content right now is
the database it already has. That is a real constraint, not a preference:
the deployed platform is a Render web service with an ephemeral filesystem,
so writing to local disk would lose every artifact on the next deploy and
would not be visible to a second gunicorn worker in the first place.

The interface below exists so that stays a swap rather than a rewrite.
An S3 backend implements the same three methods; the reference string
carries its own scheme (`db://<uuid>`, later `s3://<bucket>/<key>`), so
rows written by one backend keep resolving after another is added.

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


_backend: StorageBackend = DatabaseStorageBackend()


def get_storage_backend() -> StorageBackend:
    return _backend
