"""Minimal but genuinely valid PDFs, built in memory.

The existing suite uses `b"%PDF-fake"`, which is enough to prove an
upload endpoint accepts a content type but cannot be rendered. Visual
RAG rasterizes, so a fake would make every one of its tests pass by
skipping the code under test — the exact failure the non-fatal indexing
path is designed to tolerate, and therefore the one that would hide a
pipeline that never works at all.

Written by hand rather than with reportlab because a test fixture that
needs a dependency the project does not otherwise have is a dependency
the project now has.
"""

import io


def _object(number: int, body: bytes) -> bytes:
    return b"%d 0 obj\n%s\nendobj\n" % (number, body)


def build_pdf(pages: list[str]) -> bytes:
    """A PDF with one text-bearing page per string.

    Helvetica at 24pt, which pdfium renders without needing an embedded
    font programme — so the bytes stay small and the output is real.
    """

    if not pages:
        raise ValueError("A PDF needs at least one page.")

    page_count = len(pages)

    # Object numbering: 1 catalog, 2 page tree, 3 font, then a (page,
    # content) pair per page.
    font_number = 3
    first_page_number = 4

    page_numbers = [first_page_number + index * 2 for index in range(page_count)]
    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)

    objects: list[bytes] = [
        _object(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        _object(2, b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, page_count)),
        _object(
            font_number,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ),
    ]

    for index, text in enumerate(pages):
        page_number = page_numbers[index]
        content_number = page_number + 1

        # Escape the delimiters that would otherwise terminate the
        # string operand and corrupt the content stream.
        escaped = (
            text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ).encode("latin-1", "replace")

        stream = b"BT /F1 24 Tf 72 700 Td (%s) Tj ET" % escaped

        objects.append(
            _object(
                page_number,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (font_number, content_number),
            )
        )
        objects.append(
            _object(
                content_number,
                b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
            )
        )

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")

    # Byte offsets are recorded as each object is written. A cross
    # reference table with wrong offsets is what makes a hand-built PDF
    # open in one reader and fail in another.
    offsets: list[int] = []

    for body in objects:
        offsets.append(buffer.tell())
        buffer.write(body)

    xref_position = buffer.tell()
    total = len(objects) + 1

    buffer.write(b"xref\n0 %d\n" % total)
    buffer.write(b"0000000000 65535 f \n")

    for offset in offsets:
        buffer.write(b"%010d 00000 n \n" % offset)

    buffer.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (total, xref_position)
    )

    return buffer.getvalue()


def single_page_pdf(text: str = "Regional variance summary") -> bytes:
    return build_pdf([text])
