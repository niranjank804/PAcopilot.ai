"""S3 storage backend — isolation, selection, and the forged reference.

S3 has no notion of our tenants. The database backend gets isolation
from a WHERE clause; here it has to be an explicit check on the key
prefix, and these tests are what hold that in place.
"""

import uuid

import pytest

from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.reports.s3_storage import (
    S3StorageBackend,
    _object_key,
    _parse,
    s3_is_configured,
)
from src.reports.storage import (
    DatabaseStorageBackend,
    get_storage_backend,
    reset_storage_backend,
)

BUCKET = "pacopilot-s3"


@pytest.fixture
def s3_configured(monkeypatch):
    monkeypatch.setattr(settings, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(settings, "S3_REGION", "eu-north-1")
    reset_storage_backend()

    yield

    reset_storage_backend()


class TestReferenceFormat:

    def test_key_is_tenant_prefixed(self):
        org = uuid.uuid4()
        key = _object_key(org)

        # The prefix is the entire basis of the isolation check below.
        assert key.startswith(f"org/{org}/")

    def test_keys_are_unique_per_object(self):
        org = uuid.uuid4()

        assert _object_key(org) != _object_key(org)

    def test_parse_round_trip(self):
        assert _parse("s3://bucket/org/abc/def") == ("bucket", "org/abc/def")

    @pytest.mark.parametrize(
        "reference",
        ["", "db://abc", "s3://", "s3://bucket", "s3://bucket/", "not-a-ref",
         "s3:///key", "https://bucket/key"],
    )
    def test_malformed_references_parse_to_none(self, reference):
        assert _parse(reference) is None


class TestTenantIsolation:
    """The check that makes a forged reference useless."""

    def test_a_key_belongs_only_to_its_own_organization(self):
        backend = S3StorageBackend()
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        assert backend._belongs_to(org_a, f"org/{org_a}/file")
        assert not backend._belongs_to(org_a, f"org/{org_b}/file")

    @pytest.mark.asyncio
    async def test_reading_another_tenants_reference_is_not_found(
        self, s3_configured
    ):
        backend = S3StorageBackend()
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        forged = f"s3://{BUCKET}/org/{org_b}/{uuid.uuid4()}"

        # Must refuse before touching S3 at all — S3 would happily serve
        # this, because it has no idea who is asking.
        with pytest.raises(NotFoundException):
            await backend.get(None, organization_id=org_a, reference=forged)

    @pytest.mark.asyncio
    async def test_a_reference_to_another_bucket_is_refused(
        self, s3_configured
    ):
        backend = S3StorageBackend()
        org = uuid.uuid4()

        # Otherwise a stored value could redirect reads anywhere the
        # deployment's credentials can reach.
        elsewhere = f"s3://someone-elses-bucket/org/{org}/{uuid.uuid4()}"

        with pytest.raises(NotFoundException):
            await backend.get(None, organization_id=org, reference=elsewhere)

    @pytest.mark.asyncio
    async def test_deleting_another_tenants_object_is_a_no_op(
        self, s3_configured, monkeypatch
    ):
        """Deleting the wrong tenant's object is worse than reading it."""

        backend = S3StorageBackend()
        called = []

        monkeypatch.setattr(
            "src.reports.s3_storage._client",
            lambda: called.append(1),
        )

        await backend.delete(
            None,
            organization_id=uuid.uuid4(),
            reference=f"s3://{BUCKET}/org/{uuid.uuid4()}/file",
        )

        # Never reached the client.
        assert called == []

    @pytest.mark.asyncio
    async def test_deleting_a_malformed_reference_is_a_no_op(
        self, s3_configured
    ):
        await S3StorageBackend().delete(
            None, organization_id=uuid.uuid4(), reference="garbage"
        )


class TestBackendSelection:

    def test_the_suite_never_reaches_s3_by_default(self):
        """The invariant the autouse fixture in conftest exists for.

        Note there is no monkeypatch here — that is the point. This
        asserts what an *arbitrary* test sees on a developer machine
        with a real bucket in `.env`, which is the situation that had
        28 report tests uploading to AWS.

        A green suite is not evidence on its own: with working
        credentials those tests pass either way, and quietly leave
        objects in the production bucket. This is the only thing that
        distinguishes the two.
        """

        assert isinstance(get_storage_backend(), DatabaseStorageBackend)

    def test_database_backend_when_no_bucket_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "S3_BUCKET", None)
        reset_storage_backend()

        assert isinstance(get_storage_backend(), DatabaseStorageBackend)

        reset_storage_backend()

    def test_s3_backend_when_bucket_configured(self, s3_configured):
        assert isinstance(get_storage_backend(), S3StorageBackend)

    def test_selection_is_cached(self, s3_configured):
        assert get_storage_backend() is get_storage_backend()

    def test_s3_is_configured_reflects_the_setting(self, monkeypatch):
        monkeypatch.setattr(settings, "S3_BUCKET", None)
        assert s3_is_configured() is False

        monkeypatch.setattr(settings, "S3_BUCKET", BUCKET)
        assert s3_is_configured() is True

    def test_no_s3_client_is_built_when_unconfigured(self, monkeypatch):
        """An unconfigured deployment must not resolve AWS credentials."""

        monkeypatch.setattr(settings, "S3_BUCKET", None)
        reset_storage_backend()

        def explode():
            raise AssertionError("built an S3 client without a bucket")

        monkeypatch.setattr("src.reports.s3_storage._client", explode)

        assert isinstance(get_storage_backend(), DatabaseStorageBackend)

        reset_storage_backend()


class TestPutAndGet:

    @pytest.mark.asyncio
    async def test_put_returns_a_scheme_qualified_reference(
        self, s3_configured, monkeypatch
    ):
        captured = {}

        class FakeClient:
            def put_object(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(
            "src.reports.s3_storage._client", lambda: FakeClient()
        )

        org = uuid.uuid4()

        reference = await S3StorageBackend().put(
            None,
            organization_id=org,
            data=b"PK\x03\x04report",
            content_type="application/vnd.ms-excel",
        )

        assert reference.startswith(f"s3://{BUCKET}/org/{org}/")
        assert captured["Bucket"] == BUCKET
        assert captured["Body"] == b"PK\x03\x04report"
        # Encryption is asserted here rather than left to a bucket
        # policy, which is configuration that can drift.
        assert captured["ServerSideEncryption"] == "AES256"

    @pytest.mark.asyncio
    async def test_round_trip_through_the_fake_client(
        self, s3_configured, monkeypatch
    ):
        store = {}

        class FakeClient:
            def put_object(self, **kwargs):
                store[kwargs["Key"]] = kwargs["Body"]

            def get_object(self, Bucket, Key):  # noqa: N803 - boto3 casing
                class Body:
                    @staticmethod
                    def read():
                        return store[Key]

                return {"Body": Body}

        monkeypatch.setattr(
            "src.reports.s3_storage._client", lambda: FakeClient()
        )

        backend = S3StorageBackend()
        org = uuid.uuid4()
        payload = b"PK\x03\x04artifact-bytes"

        reference = await backend.put(
            None,
            organization_id=org,
            data=payload,
            content_type="application/pdf",
        )

        assert (
            await backend.get(None, organization_id=org, reference=reference)
            == payload
        )

    @pytest.mark.asyncio
    async def test_an_s3_error_becomes_not_found_without_leaking_detail(
        self, s3_configured, monkeypatch
    ):
        class FakeClient:
            def get_object(self, **kwargs):
                raise RuntimeError(
                    "AccessDenied for arn:aws:s3:::secret-bucket/key "
                    "requestId=ABC123"
                )

        monkeypatch.setattr(
            "src.reports.s3_storage._client", lambda: FakeClient()
        )

        org = uuid.uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await S3StorageBackend().get(
                None,
                organization_id=org,
                reference=f"s3://{BUCKET}/org/{org}/file",
            )

        # A botocore message can carry bucket, key and request id.
        message = str(exc_info.value)

        assert "AccessDenied" not in message
        assert "requestId" not in message
        assert "secret-bucket" not in message


# ======================================================================
# Live test — real bucket, real credentials. Skips without them.
# ======================================================================


def _aws_available() -> bool:
    """Whether the backend can actually authenticate.

    Both halves matter. Settings-supplied credentials come from a local
    `.env`, which pydantic-settings never exports to os.environ — so
    boto3's own chain cannot see them and asking it alone would skip this
    test on exactly the machine it was written for. The chain still has
    to be consulted second, because a deployment on an instance role
    sets neither setting and is the case this test most needs to cover.
    """

    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        return True

    try:
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:  # noqa: BLE001
        return False


requires_live_s3 = pytest.mark.skipif(
    not (_aws_available() and settings.S3_BUCKET),
    reason=(
        "live S3 unavailable: needs AWS credentials (settings or the "
        "standard chain) AND S3_BUCKET set"
    ),
)


@pytest.mark.live_aws
@requires_live_s3
class TestLiveS3:
    """Real round-trip against the configured bucket.

    Marked and skipped rather than mocked, so a green run on a machine
    without credentials can never be mistaken for proof the bucket works.
    Cleans up after itself.
    """

    @pytest.mark.asyncio
    async def test_real_round_trip_and_cleanup(self):
        backend = S3StorageBackend()
        org = uuid.uuid4()
        payload = b"PK\x03\x04pa-copilot-live-storage-test"

        reference = await backend.put(
            None,
            organization_id=org,
            data=payload,
            content_type="application/octet-stream",
        )

        try:
            assert reference.startswith(f"s3://{settings.S3_BUCKET}/org/{org}/")

            fetched = await backend.get(
                None, organization_id=org, reference=reference
            )

            assert fetched == payload

            # Isolation holds against the real service too.
            with pytest.raises(NotFoundException):
                await backend.get(
                    None, organization_id=uuid.uuid4(), reference=reference
                )
        finally:
            await backend.delete(
                None, organization_id=org, reference=reference
            )

        with pytest.raises(NotFoundException):
            await backend.get(None, organization_id=org, reference=reference)
