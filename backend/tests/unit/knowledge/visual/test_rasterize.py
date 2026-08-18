"""Rendering PDF pages.

Uses genuinely valid PDFs (tests/fixtures/pdfs.py), because a fake
`b"%PDF-..."` would make every assertion here pass without rendering
anything.
"""

import pytest

from src.core.config import settings
from src.knowledge.visual.rasterize import RasterizationError, rasterize_pdf
from tests.fixtures.pdfs import build_pdf, single_page_pdf


class TestRendering:

    @pytest.mark.asyncio
    async def test_every_page_is_rendered(self):
        pages = await rasterize_pdf(build_pdf(["One", "Two", "Three"]))

        assert len(pages) == 3

    @pytest.mark.asyncio
    async def test_pages_are_numbered_from_one(self):
        """1-based, matching what a reader sees in a PDF viewer.

        A citation that says "page 0" is wrong, and a +1 applied at
        display time is a +1 that gets forgotten in the second place it
        is needed.
        """

        pages = await rasterize_pdf(build_pdf(["One", "Two"]))

        assert [page.page_number for page in pages] == [1, 2]

    @pytest.mark.asyncio
    async def test_the_output_is_a_real_jpeg(self):
        [page] = await rasterize_pdf(single_page_pdf())

        assert page.media_type == "image/jpeg"
        assert page.image_bytes.startswith(b"\xff\xd8\xff")

    @pytest.mark.asyncio
    async def test_pages_are_in_document_order(self):
        pages = await rasterize_pdf(build_pdf(["Alpha", "Beta", "Gamma"]))

        assert [page.text for page in pages] == ["Alpha", "Beta", "Gamma"]


class TestPageAlignedText:

    @pytest.mark.asyncio
    async def test_text_belongs_to_its_own_page(self):
        """The alignment guarantee, and why one library is used.

        The reference implementation renders with pdf2image and extracts
        with pypdf, then asserts the counts match — which pairs page 7's
        text with page 7's image only for as long as two libraries never
        disagree about what a page is. Here both come from the same
        object in the same pass.
        """

        pages = await rasterize_pdf(
            build_pdf(["EMEA variance", "APAC bridge", "LATAM detail"])
        )

        assert pages[0].text == "EMEA variance"
        assert pages[1].text == "APAC bridge"
        assert pages[2].text == "LATAM detail"


class TestBounds:

    @pytest.mark.asyncio
    async def test_the_page_count_is_capped(self, monkeypatch):
        """An unbounded 900-page annual report is a self-inflicted outage.

        Every page is rendered, stored and embedded, so the cost is
        linear and needs a ceiling.
        """

        monkeypatch.setattr(settings, "VISUAL_RAG_MAX_PAGES", 2)

        pages = await rasterize_pdf(build_pdf(["One", "Two", "Three", "Four"]))

        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_images_are_capped_on_the_long_edge(self, monkeypatch):
        monkeypatch.setattr(settings, "VISUAL_RAG_MAX_IMAGE_DIMENSION", 400)

        [page] = await rasterize_pdf(single_page_pdf())

        assert max(page.width, page.height) == 400

    @pytest.mark.asyncio
    async def test_aspect_ratio_is_preserved(self, monkeypatch):
        """A squashed chart is a misread chart."""

        monkeypatch.setattr(settings, "VISUAL_RAG_MAX_IMAGE_DIMENSION", 500)

        [page] = await rasterize_pdf(single_page_pdf())

        # US Letter, 612x792.
        assert page.width / page.height == pytest.approx(612 / 792, abs=0.01)


class TestFailure:

    @pytest.mark.asyncio
    async def test_a_non_pdf_raises_a_readable_error(self):
        with pytest.raises(RasterizationError) as exc_info:
            await rasterize_pdf(b"this is not a pdf")

        # The uploader sees this, so it has to say something actionable
        # rather than surfacing a pdfium error code.
        assert "could not be opened" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_the_fake_pdf_used_elsewhere_in_the_suite_is_refused(self):
        """Guards the reason this fixture module exists.

        If `b"%PDF-fake"` ever started rendering, these tests would
        stop testing rendering.
        """

        with pytest.raises(RasterizationError):
            await rasterize_pdf(b"%PDF-fake")
