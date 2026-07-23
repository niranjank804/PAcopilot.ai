import base64
import io

import pytest
from docx import Document

from src.ai.attachment_processing import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    process_attachments,
)
from src.core.exceptions import ValidationException
from src.schemas.ai import AttachmentInput


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _fake_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_image_attachment_passes_through_natively():
    files = [AttachmentInput(filename="photo.png", content_type="image/png", data=_b64(b"fake-png-bytes"))]

    native, extracted_text = process_attachments(files)

    assert len(native) == 1
    assert native[0].filename == "photo.png"
    assert native[0].media_type == "image/png"
    assert extracted_text == ""


def test_jpg_extension_normalizes_to_image_jpeg_media_type():
    files = [AttachmentInput(filename="photo.jpg", content_type="image/jpg", data=_b64(b"fake-jpg"))]

    native, _ = process_attachments(files)

    assert native[0].media_type == "image/jpeg"


def test_pdf_attachment_passes_through_natively():
    files = [AttachmentInput(filename="report.pdf", content_type="application/pdf", data=_b64(b"%PDF-fake"))]

    native, extracted_text = process_attachments(files)

    assert len(native) == 1
    assert native[0].media_type == "application/pdf"
    assert extracted_text == ""


def test_docx_attachment_is_text_extracted_not_sent_natively():
    docx_bytes = _fake_docx_bytes("Hello from a real docx paragraph.")
    files = [AttachmentInput(filename="notes.docx", content_type="application/octet-stream", data=_b64(docx_bytes))]

    native, extracted_text = process_attachments(files)

    assert native == []
    assert "Hello from a real docx paragraph." in extracted_text
    assert "notes.docx" in extracted_text


def test_unsupported_extension_is_rejected():
    files = [AttachmentInput(filename="script.exe", content_type="application/octet-stream", data=_b64(b"x"))]

    with pytest.raises(ValidationException):
        process_attachments(files)


def test_oversized_attachment_is_rejected():
    files = [
        AttachmentInput(
            filename="huge.png",
            content_type="image/png",
            data=_b64(b"x" * (MAX_ATTACHMENT_BYTES + 1)),
        )
    ]

    with pytest.raises(ValidationException):
        process_attachments(files)


def test_too_many_attachments_is_rejected():
    files = [
        AttachmentInput(filename=f"photo{i}.png", content_type="image/png", data=_b64(b"x"))
        for i in range(MAX_ATTACHMENTS_PER_MESSAGE + 1)
    ]

    with pytest.raises(ValidationException):
        process_attachments(files)


def test_invalid_base64_is_rejected():
    files = [AttachmentInput(filename="photo.png", content_type="image/png", data="not-valid-base64!!!")]

    with pytest.raises(ValidationException):
        process_attachments(files)


def test_mixed_native_and_docx_attachments():
    docx_bytes = _fake_docx_bytes("Some extracted text.")
    files = [
        AttachmentInput(filename="photo.png", content_type="image/png", data=_b64(b"fake")),
        AttachmentInput(filename="notes.docx", content_type="application/octet-stream", data=_b64(docx_bytes)),
    ]

    native, extracted_text = process_attachments(files)

    assert len(native) == 1
    assert native[0].filename == "photo.png"
    assert "Some extracted text." in extracted_text
