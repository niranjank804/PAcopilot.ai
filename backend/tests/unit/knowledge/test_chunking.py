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


def _reference_page(name, syntax):
    return f"""{name}

Purpose: Reference entry for the {name} function.

Syntax: {syntax}

Arguments:
cube is the cube containing the value to read or write.

Example: {name} used against the Sales cube for the current period.

Notes: Argument order matters and differs between related functions.
"""


def test_function_entries_are_never_split_across_chunks():
    text = "".join(
        _reference_page(name, f"{name}(cube, elements)")
        for name in ("CELLGETN", "CELLPUTN", "CELLINCREMENTN", "CELLGETS")
    )

    chunks = chunk_text(text)

    for chunk in chunks:
        # Every chunk starts at an entry boundary, never mid-entry.
        assert chunk.splitlines()[0].strip().isupper()

    # No chunk carries a Syntax line for a function it does not introduce.
    for chunk in chunks:
        introduced = {
            line.strip()
            for line in chunk.splitlines()
            if line.strip().isupper() and line.strip()
        }
        for line in chunk.splitlines():
            if line.strip().startswith("Syntax:"):
                fn = line.split("Syntax:")[1].strip().split("(")[0]
                assert fn in introduced


def test_ti_sections_become_their_own_chunks():
    process = (
        "#Section Prolog\nsCube = 'Sales';\nnCount = 0;\n\n"
        "#Section Metadata\nDimensionElementInsertDirect('Region', '', v1, 'n');\n\n"
        "#Section Data\nCELLPUTN(v3, sCube, v1, v2);\n\n"
        "#Section Epilog\nLogOutput('INFO', 'done');\n"
    )

    chunks = chunk_text(process, chunk_size=80)

    starts = [c.splitlines()[0].strip() for c in chunks]
    assert starts == [
        "#Section Prolog",
        "#Section Metadata",
        "#Section Data",
        "#Section Epilog",
    ]


def test_markdown_headings_are_boundaries():
    text = (
        "# Naming conventions\nProcesses are prefixed with the module code.\n\n"
        "# Rule standards\nFeeders always accompany the rule they support.\n"
    )

    chunks = chunk_text(text, chunk_size=70)

    assert len(chunks) == 2
    assert chunks[0].startswith("# Naming conventions")
    assert chunks[1].startswith("# Rule standards")


def test_an_oversized_block_still_falls_back_to_fixed_width():
    text = "# Heading\n" + ("word " * 600)

    chunks = chunk_text(text, chunk_size=500, overlap=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_unstructured_prose_splits_on_paragraphs():
    text = "\n\n".join(f"Paragraph number {n} of the standards document." for n in range(6))

    chunks = chunk_text(text, chunk_size=120)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith("Paragraph number")
