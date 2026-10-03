import base64

from src.ai.schemas import Attachment
from src.core.exceptions import ValidationException
from src.knowledge.loaders.docx_loader import docx_loader
from src.schemas.ai import AttachmentInput
from src.tm1.ti.parser import parse_process

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5

_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_TYPE = "text/plain"

# Extension-based, not content_type-based — browsers are inconsistent about
# the content_type they report for the same file (e.g. "image/jpg" is not
# a real media type, several send it anyway for .jpg files).
_EXTENSION_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".docx": _DOCX_TYPE,
    # TurboIntegrator source: a `.pro` export, or code saved as text. Read
    # as text and folded into the message, like DOCX. This is how a local
    # file reaches diff_process / validate_process_code in a SaaS product —
    # the user uploads it; the server never reads anyone's filesystem.
    ".pro": _TEXT_TYPE,
    ".txt": _TEXT_TYPE,
    ".ti": _TEXT_TYPE,
}

# Characters of a text attachment kept. A large model's biggest process
# is well under this; the cap keeps one file from filling the context.
MAX_TEXT_ATTACHMENT_CHARS = 60_000


def _decode_text(raw: bytes) -> str:
    """TM1 exports are UTF-8 on v12 and often Windows-1252 on v11."""

    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _text_attachment(filename: str, raw: bytes) -> str:
    text = _decode_text(raw)

    if filename.lower().endswith(".pro"):
        # Split into the four sections the TM1 REST API uses, so the model
        # can pass them straight to diff_process or validate_process_code.
        record = parse_process(text, source_file=filename)

        if any(getattr(record, s) for s in ("prolog", "metadata", "data", "epilog")):
            parts = [
                f"[Attached TI process export: {filename}; process name "
                f"'{record.name or 'unknown'}'. Sections below are the file's "
                "own code, not the server's.]"
            ]
            for section in ("prolog", "metadata", "data", "epilog"):
                code = getattr(record, section)[:MAX_TEXT_ATTACHMENT_CHARS]
                parts.append(f"--- {section.upper()} ---\n{code}")
            return "\n".join(parts)

    return f"[Attached text file: {filename}]\n{text[:MAX_TEXT_ATTACHMENT_CHARS]}"


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
                "PDF, JPEG, PNG, DOCX and TI source (.pro, .txt, .ti) are "
                "supported."
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
        elif media_type == _TEXT_TYPE:
            extracted_text_parts.append(_text_attachment(file.filename, raw_bytes))
        else:
            native_attachments.append(
                Attachment(filename=file.filename, media_type=media_type, data=file.data)
            )

    return native_attachments, "\n\n".join(extracted_text_parts)
