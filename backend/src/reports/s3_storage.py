"""S3-backed storage for workbooks and report artifacts.

Postgres was the right first answer — there was no object store, and a
Render web service has an ephemeral filesystem — but bytea rows are read
whole into memory by asyncpg and a free-tier database is a hard ceiling.
This is the swap `StorageBackend` was built for.

Two things carry the security weight here:

**Tenant isolation is in the key, and re-checked on read.** Objects are
stored under `org/{organization_id}/{uuid}`. `get()` and `delete()`
verify that the prefix on the reference matches the *calling*
organization before touching S3 at all. Without that check a forged
reference — `s3://bucket/org/<other-org>/<uuid>` — would read another
tenant's report, because S3 itself has no idea who is asking. The
database backend gets this from a WHERE clause; here it has to be
explicit.

**boto3 is synchronous.** Every call goes through `asyncio.to_thread`,
the same discipline this codebase already uses for smtplib and TM1py, so
a slow or unreachable bucket cannot block the event loop.

Credentials are never read from application config. boto3 resolves them
from the standard chain (environment, shared credentials file, instance
role), which means an EC2/ECS deployment can use a role and never hold a
long-lived key at all — and no key ever passes through a settings object
that might be logged or serialized.
"""

import asyncio
import uuid
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.core.logging import app_logger
from src.reports.storage import StorageBackend

_S3_SCHEME = "s3://"


@lru_cache(maxsize=1)
def _client():
    """One client per process.

    boto3 clients are thread-safe and expensive to build; creating one
    per request would add a credential-resolution round trip to every
    upload.
    """

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=settings.S3_REGION,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


def _object_key(organization_id: uuid.UUID) -> str:
    """Tenant-prefixed key. The prefix is what makes isolation checkable."""

    return f"org/{organization_id}/{uuid.uuid4()}"


def _parse(reference: str) -> tuple[str, str] | None:
    """Split `s3://bucket/key` into (bucket, key), or None."""

    if not reference or not reference.startswith(_S3_SCHEME):
        return None

    remainder = reference[len(_S3_SCHEME) :]
    bucket, separator, key = remainder.partition("/")

    if not separator or not bucket or not key:
        return None

    return bucket, key


class S3StorageBackend(StorageBackend):

    async def put(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        data: bytes,
        content_type: str,
    ) -> str:
        bucket = settings.S3_BUCKET
        key = _object_key(organization_id)

        def _upload() -> None:
            _client().put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Defence in depth: the bucket should also enforce this,
                # but a bucket policy is configuration that can drift and
                # this cannot.
                ServerSideEncryption="AES256",
            )

        await asyncio.to_thread(_upload)

        return f"{_S3_SCHEME}{bucket}/{key}"

    async def get(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> bytes:
        bucket, key = self._resolve(organization_id, reference)

        def _download() -> bytes:
            response = _client().get_object(Bucket=bucket, Key=key)

            return response["Body"].read()

        try:
            return await asyncio.to_thread(_download)
        except Exception as exc:  # noqa: BLE001
            # Type only. A botocore error message can carry the bucket,
            # key and request id, and the caller only needs to know it
            # is not there.
            app_logger.warning(
                f"s3 storage: object unavailable ({type(exc).__name__})"
            )

            raise NotFoundException("The stored file could not be found.")

    async def delete(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        reference: str,
    ) -> None:
        parsed = _parse(reference)

        if parsed is None:
            return

        bucket, key = parsed

        # Same isolation check as get(): deleting another tenant's object
        # would be worse than reading it.
        if not self._belongs_to(organization_id, key):
            return

        def _delete() -> None:
            _client().delete_object(Bucket=bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:  # noqa: BLE001
            # Idempotent by contract — deleting twice is not an error.
            app_logger.warning(
                f"s3 storage: delete failed ({type(exc).__name__})"
            )

    @staticmethod
    def _belongs_to(organization_id: uuid.UUID, key: str) -> bool:
        return key.startswith(f"org/{organization_id}/")

    def _resolve(
        self, organization_id: uuid.UUID, reference: str
    ) -> tuple[str, str]:
        parsed = _parse(reference)

        if parsed is None:
            raise NotFoundException("The stored file could not be found.")

        bucket, key = parsed

        # The check that makes a forged reference useless. S3 has no
        # notion of our tenants, so this is the only thing standing
        # between `s3://bucket/org/<someone-else>/<uuid>` and their data.
        if not self._belongs_to(organization_id, key):
            raise NotFoundException("The stored file could not be found.")

        # Refuse a reference pointing at some other bucket entirely,
        # which would otherwise let a stored value redirect reads
        # anywhere the deployment's credentials can reach.
        if bucket != settings.S3_BUCKET:
            raise NotFoundException("The stored file could not be found.")

        return bucket, key


def s3_is_configured() -> bool:
    return bool(settings.S3_BUCKET)
