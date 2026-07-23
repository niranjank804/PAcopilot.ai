from src.knowledge.chunking import chunk_text


def test_chunk_text_returns_empty_list_for_blank_text():
    assert chunk_text("   ") == []


def test_chunk_text_returns_single_chunk_for_short_text():
    chunks = chunk_text("hello world", chunk_size=1000, overlap=100)

    assert chunks == ["hello world"]


def test_chunk_text_splits_with_overlap():
    text = "a" * 2500

    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) == 3
    assert all(len(chunk) <= 1000 for chunk in chunks)
