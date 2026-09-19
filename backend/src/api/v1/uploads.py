"""Issue signed URLs so files travel client <-> S3, never through the API.

Any signed-in user may ask for one: the key it returns is scoped to
their organization's upload area, and every endpoint that consumes an
upload re-checks that scope and its own permission.
"""

from fastapi import APIRouter, Depends

from src.api.dependencies.auth import get_current_user
from src.core.config import settings
from src.core.exceptions import ServiceUnavailableException, ValidationException
from src.reports.s3_storage import presign_upload, s3_is_configured, upload_object_key
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.schemas.uploads import UploadRequest, UploadTarget

router = APIRouter(prefix="/uploads", tags=["Uploads"])


def issue_upload_target(organization_id, payload: UploadRequest) -> UploadTarget:
    if not s3_is_configured():
        raise ServiceUnavailableException(
            "Direct upload is not configured on this server.",
            code="DIRECT_UPLOAD_UNAVAILABLE",
        )

    if payload.size_bytes > settings.DIRECT_UPLOAD_MAX_BYTES:
        limit_mb = settings.DIRECT_UPLOAD_MAX_BYTES // (1024 * 1024)

        raise ValidationException(f"File exceeds the {limit_mb}MB upload limit.")

    key = upload_object_key(organization_id, payload.filename)
    ttl = settings.DIRECT_UPLOAD_URL_TTL_SECONDS
    target = presign_upload(key, content_type=payload.content_type, expires_in=ttl)

    return UploadTarget(key=key, url=target["url"], headers=target["headers"], expires_in=ttl)


@router.post("", response_model=ApiResponse[UploadTarget], status_code=201)
async def create_upload(
    payload: UploadRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    return ApiResponse(
        success=True,
        data=issue_upload_target(current_user.organization_id, payload),
    )
