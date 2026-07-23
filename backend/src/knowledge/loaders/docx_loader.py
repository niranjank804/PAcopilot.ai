import io

from docx import Document

from src.knowledge.loaders.base import DocumentLoader


class DocxLoader(DocumentLoader):

    def load(self, file_bytes: bytes) -> str:
        document = Document(io.BytesIO(file_bytes))

        paragraphs = [paragraph.text for paragraph in document.paragraphs]

        return "\n".join(paragraphs).strip()


docx_loader = DocxLoader()
