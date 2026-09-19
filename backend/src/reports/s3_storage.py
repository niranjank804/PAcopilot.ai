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

**Credentials stay boto3's job wherever possible.** It resolves them
from the standard chain — process environment, shared credentials file,
instance role — so an EC2/ECS deployment can use a role and never hold a
long-lived key at all. On a host like Render the dashboard's env vars
*are* the process environment, so that path needs no configuration here
either.

Local development is the exception, and the reason `AWS_ACCESS_KEY_ID`
and `AWS_SECRET_ACCESS_KEY` are declared in settings: a `.env` file is
read by pydantic-settings into the settings object and never exported to
os.environ, so boto3 cannot see it. When both are set they are passed to
the client explicitly; when either is absent nothing is passed and the
chain decides, which keeps the instance-role deployment key-free.
"""

import asyncio
import re
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

    # Explicit only when configured. Passing None lets boto3 fall back to
    # its own chain, which is what an instance-role deployment needs —
    # so this supports a local .env without forcing a long-lived key in
    # production.
    credentials = {}

    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        credentials = {
            "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
        }

    return boto3.client(
        "s3",
        region_name=settings.S3_REGION,
        **credentials,
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

# --- Direct transfers ------------------------------------------------------
#
# Vercel caps a function's request and response body at 4.5 MB, and a
# knowledge document, a workbook, an artifact or a chat attachment can be
# ten times that. So the browser (or the worker) moves the bytes to and
# from S3 itself, with URLs this module signs, and the API only ever
# handles keys. Every key is tenant-prefixed and checked before use, and
# a temporary upload is deleted once the API has consumed it.

_UPLOAD_SEGMENT = "uploads"


def upload_object_key(organization_id: uuid.UUID, filename: str) -> str:
    """A fresh, tenant-prefixed key for a file the client is about to put."""

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "file"

    return f"org/{organization_id}/{_UPLOAD_SEGMENT}/{uuid.uuid4()}/{safe[:120]}"


def is_upload_key_for(organization_id: uuid.UUID, key: str) -> bool:
    """Only keys this organization was issued, and only in the upload
    area — never a stored artifact's key, which would let a presigned
    upload overwrite one."""

    return key.startswith(f"org/{organization_id}/{_UPLOAD_SEGMENT}/") and ".." not in key


def presign_upload(key: str, *, content_type: str, expires_in: int) -> dict:
    """A PUT URL plus the headers the client must send with it. The
    headers are part of the signature, so encryption at rest is enforced
    by the URL itself rather than trusted to the client."""

    url = _client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ContentType": content_type,
            "ServerSideEncryption": "AES256",
        },
        ExpiresIn=expires_in,
    )

    return {
        "url": url,
        "headers": {
            "Content-Type": content_type,
            "x-amz-server-side-encryption": "AES256",
        },
    }


def presign_download(
    reference: str,
    *,
    filename: str,
    content_type: str,
    expires_in: int,
) -> str | None:
    """A GET URL for a stored object, or None when the reference is not
    in S3 (the database backend), so the caller can fall back to
    streaming it."""

    parsed = _parse(reference)

    if parsed is None:
        return None

    bucket, key = parsed

    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
            "ResponseContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


async def read_upload(organization_id: uuid.UUID, key: str) -> bytes:
    """The bytes a client put under a key it was issued."""

    if not is_upload_key_for(organization_id, key):
        raise NotFoundException("Upload not found.")

    def _read() -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = _client().get_object(Bucket=settings.S3_BUCKET, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFoundException("Upload not found.") from exc

            raise

        return response["Body"].read()

    return await asyncio.to_thread(_read)


async def delete_upload(key: str) -> None:
    """Remove a consumed upload. Best effort: an object left behind costs
    cents, while failing the request it belonged to would cost the user
    the upload."""

    def _delete() -> None:
        try:
            _client().delete_object(Bucket=settings.S3_BUCKET, Key=key)
        except Exception:
            pass

    await asyncio.to_thread(_delete)
