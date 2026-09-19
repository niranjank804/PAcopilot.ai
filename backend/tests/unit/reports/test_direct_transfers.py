"""Signed transfers: the part of the S3 backend Vercel made necessary."""

import uuid

import pytest

import src.reports.s3_storage as s3
from src.core.config import settings
from src.core.exceptions import NotFoundException


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://s3.test/{Params['Bucket']}/{Params['Key']}?op={operation}&ttl={ExpiresIn}"

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

        class Body:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

        return {"Body": Body(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3()
    monkeypatch.setattr(settings, "S3_BUCKET", "pacopilot-test")
    monkeypatch.setattr(s3, "_client", lambda: client)

    return client


def test_upload_keys_are_scoped_to_the_organization():
    org, other = uuid.uuid4(), uuid.uuid4()
    key = s3.upload_object_key(org, "Q3 Plan (final).xlsx")

    assert s3.is_upload_key_for(org, key)
    assert not s3.is_upload_key_for(other, key)
    # A stored artifact's key is not an upload key, so a presigned PUT
    # can never be pointed at one.
    assert not s3.is_upload_key_for(org, f"org/{org}/{uuid.uuid4()}")
    # Spaces and brackets become underscores; the extension survives.
    assert key.endswith(".xlsx")
    assert " " not in key and "(" not in key


def test_presigned_upload_pins_encryption_into_the_signature(fake_s3):
    target = s3.presign_upload("org/x/uploads/1/a.pdf", content_type="application/pdf", expires_in=60)

    assert target["url"].startswith("https://s3.test/pacopilot-test/org/x/uploads/1/a.pdf")
    assert target["headers"]["x-amz-server-side-encryption"] == "AES256"
    assert target["headers"]["Content-Type"] == "application/pdf"


def test_presigned_download_is_none_for_database_references(fake_s3):
    assert s3.presign_download("db://abc", filename="a", content_type="text/plain", expires_in=60) is None
    assert s3.presign_download("s3://b/k", filename="a", content_type="text/plain", expires_in=60).startswith("https://s3.test/b/k")


@pytest.mark.asyncio
async def test_read_upload_refuses_another_organizations_key(fake_s3):
    org, other = uuid.uuid4(), uuid.uuid4()
    key = s3.upload_object_key(other, "secret.pdf")
    fake_s3.objects[key] = b"theirs"

    with pytest.raises(NotFoundException):
        await s3.read_upload(org, key)


@pytest.mark.asyncio
async def test_read_upload_returns_the_bytes_and_delete_removes_them(fake_s3):
    org = uuid.uuid4()
    key = s3.upload_object_key(org, "doc.pdf")
    fake_s3.objects[key] = b"%PDF"

    assert await s3.read_upload(org, key) == b"%PDF"

    await s3.delete_upload(key)

    assert key in fake_s3.deleted
    with pytest.raises(NotFoundException):
        await s3.read_upload(org, key)
