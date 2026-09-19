"""POST /uploads: a signed URL, or an honest 503 where S3 is not set up."""

import pytest

import src.reports.s3_storage as s3
from src.core.config import settings
from tests.fixtures.factories import auth_headers, create_org_admin


class FakeS3:
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://s3.test/{Params['Key']}"


@pytest.mark.asyncio
async def test_uploads_are_unavailable_without_s3(client, db_session, monkeypatch):
    org, admin = await create_org_admin(db_session)
    monkeypatch.setattr(settings, "S3_BUCKET", None)

    response = await client.post(
        "/uploads",
        json={"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10},
        headers=auth_headers(admin),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DIRECT_UPLOAD_UNAVAILABLE"


@pytest.mark.asyncio
async def test_uploads_issue_a_tenant_scoped_target(client, db_session, monkeypatch):
    org, admin = await create_org_admin(db_session)
    monkeypatch.setattr(settings, "S3_BUCKET", "pacopilot-test")
    monkeypatch.setattr(s3, "_client", lambda: FakeS3())

    response = await client.post(
        "/uploads",
        json={"filename": "plan.xlsx", "content_type": "application/octet-stream", "size_bytes": 10},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["key"].startswith(f"org/{org.id}/uploads/")
    assert data["url"].startswith("https://s3.test/")
    assert data["headers"]["x-amz-server-side-encryption"] == "AES256"


@pytest.mark.asyncio
async def test_uploads_refuse_oversized_files(client, db_session, monkeypatch):
    org, admin = await create_org_admin(db_session)
    monkeypatch.setattr(settings, "S3_BUCKET", "pacopilot-test")
    monkeypatch.setattr(s3, "_client", lambda: FakeS3())

    response = await client.post(
        "/uploads",
        json={"filename": "huge.bin", "content_type": "application/octet-stream", "size_bytes": settings.DIRECT_UPLOAD_MAX_BYTES + 1},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_uploads_require_a_session(client):
    response = await client.post(
        "/uploads",
        json={"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10},
    )

    assert response.status_code == 401
