"""Turn upload keys on chat attachments into the bytes the model reads.

Runs in the API layer, before the orchestrator, so the orchestrator and
attachment processing still see exactly the inline shape they always
did. Each consumed upload is deleted from the upload area.
"""

import base64
import uuid

from src.core.exceptions import ValidationException
from src.reports.s3_storage import delete_upload, read_upload
from src.schemas.ai import AttachmentInput

# The composer's own cap. Enforced here as well because a signed URL
# accepts any size the bucket allows.
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


async def resolve_uploaded_attachments(
    attachments: list[AttachmentInput] | None,
    organization_id: uuid.UUID,
) -> list[AttachmentInput] | None:
    if not attachments:
        return attachments

    resolved: list[AttachmentInput] = []

    for attachment in attachments:
        if attachment.data is not None:
            resolved.append(attachment)
            continue

        key = attachment.upload_key or ""
        raw = await read_upload(organization_id, key)
        await delete_upload(key)

        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise ValidationException(
                f'"{attachment.filename}" is too large — attachments are capped at 15MB.'
            )

        resolved.append(
            AttachmentInput(
                filename=attachment.filename,
                content_type=attachment.content_type,
                data=base64.b64encode(raw).decode("ascii"),
            )
        )

    return resolved
