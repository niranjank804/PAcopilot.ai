import io

from src.knowledge.loaders.base import DocumentLoader


class DocxLoader(DocumentLoader):

    def load(self, file_bytes: bytes) -> str:
        # Imported here: only document uploads need it, and every cold
        # start would pay for it otherwise.
        from docx import Document

        document = Document(io.BytesIO(file_bytes))

        paragraphs = [paragraph.text for paragraph in document.paragraphs]

        return "\n".join(paragraphs).strip()


docx_loader = DocxLoader()
