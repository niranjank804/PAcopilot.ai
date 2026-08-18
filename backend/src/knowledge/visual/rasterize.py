"""PDF pages to images.

Visual retrieval starts by *not* extracting text. `pdf_loader` reads a
PDF with pypdf and returns a flat string, which is the right thing for
prose and the wrong thing for the documents this product deals with: a
Planning Analytics variance pack is mostly tables, charts and pivot
exports, and text extraction returns their contents as an unordered
column of numbers with the row and column headings that gave them
meaning discarded. A page image keeps the layout, and both ColPali and
Claude read layout directly.

pypdfium2 (Chrome's PDF engine) does the rasterising. It was already a
declared dependency, and unlike pdf2image — which the reference
implementation uses — it needs no poppler binary on PATH, which is what
makes this work unchanged on Windows workers and a Linux container.
"""

import asyncio
import io

import pypdfium2

from src.core.config import settings


class RenderedPage:

    def __init__(
        self,
        page_number: int,
        image_bytes: bytes,
        width: int,
        height: int,
        text: str,
    ):
        # 1-based, matching what a reader sees in a PDF viewer. The
        # reference implementation stored 0-based and added 1 only when
        # printing, which is the kind of split that eventually shows a
        # user a citation one page off.
        self.page_number = page_number
        self.image_bytes = image_bytes
        self.width = width
        self.height = height
        # Extracted from the same library, in the same pass, so it is
        # the text of *this* image by construction. The reference
        # implementation renders with pdf2image and extracts with pypdf,
        # then asserts the two counts match — which pairs page 7's text
        # with page 7's picture only as long as neither library ever
        # disagrees about what counts as a page.
        self.text = text

    @property
    def media_type(self) -> str:
        return "image/jpeg"


class RasterizationError(Exception):
    ...


def _render(file_bytes: bytes, *, dpi: int, max_pages: int, max_dimension: int) -> list[RenderedPage]:
    """Blocking. Call through `rasterize_pdf`."""

    try:
        document = pypdfium2.PdfDocument(file_bytes)
    except Exception as exc:
        raise RasterizationError(
            "This PDF could not be opened for rendering. It may be "
            "corrupt or password-protected."
        ) from exc

    pages: list[RenderedPage] = []

    try:
        total = len(document)

        if total == 0:
            raise RasterizationError("This PDF has no pages.")

        for index in range(min(total, max_pages)):
            page = document[index]

            try:
                image = page.render(scale=dpi / 72).to_pil().convert("RGB")

                textpage = page.get_textpage()

                try:
                    text = textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
            finally:
                page.close()

            # Two consumers, one ceiling. ColPali resizes to its own
            # patch grid anyway, and Claude downsamples anything wider
            # than ~1568px before charging for it — so pixels above this
            # cost storage and upload time while changing neither
            # result. Aspect ratio is preserved because a squashed chart
            # is a misread chart.
            if max(image.size) > max_dimension:
                scale = max_dimension / max(image.size)
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                )

            buffer = io.BytesIO()
            # JPEG, not PNG: a rendered page is photographic enough that
            # PNG runs several times larger for no visible gain, and
            # these are stored per page per document.
            image.save(buffer, format="JPEG", quality=80, optimize=True)

            pages.append(
                RenderedPage(
                    page_number=index + 1,
                    image_bytes=buffer.getvalue(),
                    width=image.width,
                    height=image.height,
                    text=text.strip(),
                )
            )
    finally:
        document.close()

    return pages


async def rasterize_pdf(file_bytes: bytes) -> list[RenderedPage]:
    """Render each page to a JPEG.

    Off the event loop: rendering is CPU-bound C code that holds the GIL
    for long enough to stall every other request on the worker, and a
    30-page document is seconds of it. Same discipline the S3 backend
    and TM1py calls already follow.
    """

    return await asyncio.to_thread(
        _render,
        file_bytes,
        dpi=settings.VISUAL_RAG_RENDER_DPI,
        max_pages=settings.VISUAL_RAG_MAX_PAGES,
        max_dimension=settings.VISUAL_RAG_MAX_IMAGE_DIMENSION,
    )
