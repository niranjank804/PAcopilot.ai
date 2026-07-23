def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> list[str]:

    text = text.strip()

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        chunks.append(text[start:end].strip())

        if end >= len(text):
            break

        start = end - overlap

    return [chunk for chunk in chunks if chunk]
