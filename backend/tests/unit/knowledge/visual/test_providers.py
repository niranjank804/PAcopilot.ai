"""Provider selection and availability.

`availability()` carries most of the weight here. ColPali cannot run on
the deployment this product ships to, so "can this run?" is a real
question with a deployment-dependent answer, and the answer has to reach
a user as an explanation rather than as an ImportError or an OOM kill.
"""

import pytest

from src.ai.exceptions import AIProviderError
from src.core.config import settings
from src.knowledge.visual.providers.colpali_local import colpali_visual_provider
from src.knowledge.visual.providers.registry import (
    VISUAL_PROVIDERS,
    get_visual_provider,
    visual_rag_availability,
)
from src.knowledge.visual.providers.text_proxy import (
    MINIMUM_TEXT_CHARACTERS,
    text_proxy_visual_provider,
)
from src.knowledge.visual.rasterize import RenderedPage


def _page(number: int, text: str) -> RenderedPage:
    return RenderedPage(
        page_number=number,
        image_bytes=b"\xff\xd8\xff-not-decoded-by-this-provider",
        width=100,
        height=100,
        text=text,
    )


class TestRegistry:

    def test_both_providers_are_registered(self):
        assert set(VISUAL_PROVIDERS) == {"text-proxy", "colpali"}

    def test_the_configured_provider_is_the_default(self, monkeypatch):
        monkeypatch.setattr(settings, "VISUAL_RAG_PROVIDER", "colpali")

        assert get_visual_provider().name == "colpali"

    def test_an_unknown_provider_names_the_known_ones(self, monkeypatch):
        monkeypatch.setattr(settings, "VISUAL_RAG_PROVIDER", "colqwen")

        with pytest.raises(AIProviderError) as exc_info:
            get_visual_provider()

        assert "text-proxy" in str(exc_info.value)

    def test_disabling_the_feature_reports_it_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "VISUAL_RAG_ENABLED", False)

        availability = visual_rag_availability()

        assert availability.available is False
        assert "disabled" in availability.reason.lower()


class TestProviderNamesArePersisted:

    def test_names_are_stable(self):
        """These strings are written into every row.

        Renaming one silently orphans every page indexed under the old
        name, because retrieval filters on it — the pages stay in the
        table and never match again.
        """

        assert text_proxy_visual_provider.name == "text-proxy"
        assert colpali_visual_provider.name == "colpali"


class TestTextProxy:

    def test_it_is_unavailable_without_an_embedding_key(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

        availability = text_proxy_visual_provider.availability()

        assert availability.available is False
        assert "OPENAI_API_KEY" in availability.reason

    @pytest.mark.asyncio
    async def test_a_text_poor_page_gets_no_embedding(self, monkeypatch):
        """A scan or a full-page figure.

        Embedding the few characters it did yield would place it
        arbitrarily in the vector space and let it surface for unrelated
        queries. It is stored without one instead, and simply never
        retrieved by this provider.
        """

        class Recording:
            def __init__(self):
                self.calls = []

            async def embed(self, texts):
                self.calls.append(texts)
                return [[1.0, 0.0, 0.0] for _ in texts]

        recording = Recording()
        monkeypatch.setitem(
            __import__(
                "src.knowledge.embeddings.registry", fromlist=["EMBEDDING_PROVIDERS"]
            ).EMBEDDING_PROVIDERS,
            "openai",
            recording,
        )

        pages = [
            _page(1, "x" * (MINIMUM_TEXT_CHARACTERS + 10)),
            _page(2, "too short"),
        ]

        import uuid

        result = await text_proxy_visual_provider.embed_pages(
            pages, organization_id=uuid.uuid4()
        )

        assert result[0].shape == (1, 3)
        assert result[1].size == 0
        # The short page cost nothing.
        assert recording.calls == [[pages[0].text]]

    @pytest.mark.asyncio
    async def test_no_api_call_when_every_page_is_text_poor(self, monkeypatch):
        class Exploding:
            async def embed(self, texts):
                raise AssertionError("should not have been called")

        monkeypatch.setitem(
            __import__(
                "src.knowledge.embeddings.registry", fromlist=["EMBEDDING_PROVIDERS"]
            ).EMBEDDING_PROVIDERS,
            "openai",
            Exploding(),
        )

        import uuid

        result = await text_proxy_visual_provider.embed_pages(
            [_page(1, "short")], organization_id=uuid.uuid4()
        )

        assert result[0].size == 0


class TestColPaliAvailability:

    def test_it_explains_a_missing_dependency_rather_than_raising(self):
        """torch is not installed here, and that must not be an
        ImportError at boot — this module is imported by the registry on
        every start, including on the container that has neither
        torch nor a GPU.
        """

        availability = colpali_visual_provider.availability()

        assert availability.available is False
        assert "colpali-engine" in availability.reason or "torch" in availability.reason

    def test_the_reason_points_somewhere(self):
        """A user reading this needs to know what to do next."""

        assert "docs/" in colpali_visual_provider.availability().reason

    def test_importing_the_module_does_not_require_torch(self):
        """The guarantee that keeps the free deployment booting.

        A top-level `import torch` here would turn an absent optional
        dependency into a failed application start.
        """

        import src.knowledge.visual.providers.colpali_local as module

        source = open(module.__file__, encoding="utf-8").read()
        header = source.split("class ColPaliVisualProvider")[0]

        assert "\nimport torch" not in header
        assert "\nfrom colpali_engine" not in header
