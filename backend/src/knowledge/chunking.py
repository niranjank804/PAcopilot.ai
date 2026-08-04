"""Split documents on their own structure, not on character counts.

Fixed-width windows cut wherever 1000 characters happen to land. For the
two document kinds this knowledge base actually holds, that lands badly:

* **Function references.** A window that ends mid-entry produces a chunk
  holding one function's name and the next function's `Syntax:` line.
  Retrieved for a question about the first function, it supplies the
  second one's signature — a wrong answer delivered with a citation.
* **TI processes and rules.** Prolog, Metadata, Data and Epilog are the
  real units. Splitting mid-section separates a variable's assignment
  from its use, and a rule from the feeder that supports it.

So text is broken into semantic blocks first, blocks are packed into
chunks up to `chunk_size`, and a block is only ever cut when it exceeds
`chunk_size` on its own. Overlap applies to that fallback path only —
between semantic blocks it adds duplicated text without adding context.
"""

import re

# '#Section Prolog' and friends: the four TI tabs, as exported by TM1.
_TI_SECTION = re.compile(r"^\s*#Section\s+\w+", re.IGNORECASE)

# Markdown ATX headings, and the bare ALL-CAPS or Title-case line that
# function reference pages use as an entry header.
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+\S")

# A line that is just a function-style identifier — 'CELLGETN',
# 'AddClient', 'SUBST' — which is how reference entries start when the
# source has no markdown structure left.
_ENTRY_HEADING = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,40}\s*$")

# A heading is only a boundary if the entry under it looks like a
# reference body; otherwise every short line in prose becomes a split.
_REFERENCE_MARKER = re.compile(
    r"^\s*(syntax|purpose|arguments?|example|returns?|description|note)s?\s*[:\-]",
    re.IGNORECASE,
)


def _is_boundary(line: str, next_lines: list[str]) -> bool:
    if _TI_SECTION.match(line):
        return True

    if _MARKDOWN_HEADING.match(line):
        return True

    if _ENTRY_HEADING.match(line):
        # Look ahead a few lines: a lone capitalised word followed by
        # 'Syntax:' or 'Purpose:' is a reference entry header. The same
        # word inside a paragraph is not.
        return any(_REFERENCE_MARKER.match(peek) for peek in next_lines[:4])

    return False


def _blocks(text: str) -> list[str]:
    """Split into semantic blocks: sections, headings, then paragraphs."""

    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []

    for index, line in enumerate(lines):
        if current and _is_boundary(line, lines[index + 1 :]):
            blocks.append(current)
            current = []

        current.append(line)

    if current:
        blocks.append(current)

    joined = ["\n".join(block).strip() for block in blocks]
    structured = [block for block in joined if block]

    # Nothing structural to go on — fall back to paragraphs so packing
    # still has units smaller than the whole document.
    if len(structured) <= 1:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text)]
        return [p for p in paragraphs if p]

    return structured


def _split_oversized(block: str, chunk_size: int, overlap: int) -> list[str]:
    """Last resort for a single block bigger than one chunk."""

    pieces = []
    start = 0

    while start < len(block):
        end = start + chunk_size
        pieces.append(block[start:end].strip())

        if end >= len(block):
            break

        start = end - overlap

    return [piece for piece in pieces if piece]


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> list[str]:

    text = text.strip()

    if not text:
        return []

    chunks: list[str] = []
    current = ""

    for block in _blocks(text):
        if len(block) > chunk_size:
            if current:
                chunks.append(current)
                current = ""

            chunks.extend(_split_oversized(block, chunk_size, overlap))
            continue

        candidate = f"{current}\n\n{block}" if current else block

        if len(candidate) > chunk_size:
            chunks.append(current)
            current = block
        else:
            current = candidate

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]
