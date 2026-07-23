from src.knowledge.loaders.base import DocumentLoader


class TextLoader(DocumentLoader):

    def load(self, file_bytes: bytes) -> str:
        return file_bytes.decode("utf-8", errors="replace").strip()


text_loader = TextLoader()
