import io

from pypdf import PdfReader

from src.knowledge.loaders.base import DocumentLoader


class PDFLoader(DocumentLoader):

    def load(self, file_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(file_bytes))

        pages = [page.extract_text() or "" for page in reader.pages]

        return "\n\n".join(pages).strip()


pdf_loader = PDFLoader()
