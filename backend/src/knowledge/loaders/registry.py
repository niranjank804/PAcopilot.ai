from src.core.exceptions import ValidationException
from src.knowledge.loaders.base import DocumentLoader
from src.knowledge.loaders.docx_loader import docx_loader
from src.knowledge.loaders.pdf_loader import pdf_loader
from src.knowledge.loaders.text_loader import text_loader

LOADERS: dict[str, DocumentLoader] = {
    "application/pdf": pdf_loader,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": docx_loader,
    "text/plain": text_loader,
    "text/markdown": text_loader,
}

EXTENSION_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def resolve_content_type(
    filename: str,
    provided_content_type: str | None,
) -> str:

    if provided_content_type in LOADERS:
        return provided_content_type

    for extension, content_type in EXTENSION_CONTENT_TYPES.items():
        if filename.lower().endswith(extension):
            return content_type

    return provided_content_type or "application/octet-stream"


def get_loader(content_type: str) -> DocumentLoader:
    loader = LOADERS.get(content_type)

    if loader is None:
        raise ValidationException(
            f"Unsupported document type: {content_type}"
        )

    return loader
