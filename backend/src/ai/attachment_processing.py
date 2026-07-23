import base64

from src.ai.schemas import Attachment
from src.core.exceptions import ValidationException
from src.knowledge.loaders.docx_loader import docx_loader
from src.schemas.ai import AttachmentInput

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5

_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Extension-based, not content_type-based — browsers are inconsistent about
# the content_type they report for the same file (e.g. "image/jpg" is not
# a real media type, several send it anyway for .jpg files).
_EXTENSION_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".docx": _DOCX_TYPE,
}


def process_attachments(
    files: list[AttachmentInput],
) -> tuple[list[Attachment], str]:
    """Splits incoming attachments into what Claude can read natively
    (images, PDFs — real vision/document understanding, not OCR) and DOCX,
    whose text is extracted server-side (reusing the Knowledge Base's own
    loader) since Claude has no native Word-document content type.

    Returns (native_attachments_for_the_ai_call, extracted_text_to_append).
    """

    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValidationException(
            f"Too many attachments — max {MAX_ATTACHMENTS_PER_MESSAGE} per message."
        )

    native_attachments: list[Attachment] = []
    extracted_text_parts: list[str] = []

    for file in files:
        extension = (
            "." + file.filename.rsplit(".", 1)[-1].lower()
            if "." in file.filename
            else ""
        )
        media_type = _EXTENSION_MEDIA_TYPE.get(extension)

        if media_type is None:
            raise ValidationException(
                f"Unsupported attachment type for '{file.filename}' — only "
                "PDF, JPEG, PNG, and DOCX are supported."
            )

        try:
            raw_bytes = base64.b64decode(file.data)
        except Exception as exc:
            raise ValidationException(
                f"Could not decode attachment '{file.filename}'."
            ) from exc

        if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
            raise ValidationException(
                f"'{file.filename}' is too large — attachments are capped "
                f"at {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB."
            )

        if media_type == _DOCX_TYPE:
            text = docx_loader.load(raw_bytes)
            extracted_text_parts.append(f"[Attached document: {file.filename}]\n{text}")
        else:
            native_attachments.append(
                Attachment(filename=file.filename, media_type=media_type, data=file.data)
            )

    return native_attachments, "\n\n".join(extracted_text_parts)
