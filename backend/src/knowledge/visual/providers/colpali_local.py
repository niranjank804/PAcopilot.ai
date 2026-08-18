"""ColPali, in this process, with late interaction intact.

`vidore/colpali-v1.3` is PaliGemma-3B with a projection to 128-dim
patch embeddings. It emits one vector per image patch (~1030 for a
page) and one per query token, and those are kept whole — the mean
pooling that most implementations apply here is what removes ColPali's
only advantage over ordinary embedding search. See
`late_interaction.py` for the test that pins why.

**This cannot run on the free deployment.** The weights are ~6GB in
bfloat16 and the container has 512MB and no GPU, so `availability()`
reports what is missing rather than letting the process be OOM-killed
mid-request. It is intended for a machine with a GPU: a developer
workstation, a self-hosted install, or — the natural home given this
codebase already has a worker plane with job claiming and leases — a
GPU-equipped report worker.

torch and colpali_engine are imported inside the methods, never at
module scope. This module is imported by the provider registry on every
boot, including on the container that has neither installed, and a
top-level import would turn an absent optional dependency into a failed
application start.
"""

import asyncio
import io
import uuid

import numpy as np

from src.core.config import settings
from src.core.logging import app_logger
from src.knowledge.visual.late_interaction import normalize
from src.knowledge.visual.providers.base import Availability, VisualEmbeddingProvider
from src.knowledge.visual.rasterize import RenderedPage

MODEL_NAME = "vidore/colpali-v1.3"

# Pages per forward pass. Activation memory scales with this, and the
# reference implementation's 2 is a reasonable floor for an 8GB card.
BATCH_SIZE = 2


def _dependencies_present() -> tuple[bool, str]:
    from importlib.util import find_spec

    for module, package in (("torch", "torch"), ("colpali_engine", "colpali-engine")):
        if find_spec(module) is None:
            return False, (
                f"ColPali needs the optional '{package}' package, which is "
                "not installed. See docs/knowledge/VISUAL-RAG.md."
            )

    return True, ""


class ColPaliVisualProvider(VisualEmbeddingProvider):

    name = "colpali"

    def __init__(self):
        self._model = None
        self._processor = None
        # One model per process, loaded on first use. Loading costs
        # seconds and gigabytes, so it must not happen at import, and
        # must not happen twice.
        self._lock = asyncio.Lock()

    def availability(self) -> Availability:
        present, reason = _dependencies_present()

        if not present:
            return Availability(False, reason)

        import torch

        if not (torch.cuda.is_available() or torch.backends.mps.is_available()):
            if settings.VISUAL_RAG_ALLOW_CPU_COLPALI:
                return Availability(
                    True,
                    "Running ColPali on CPU — expect roughly 10-30 seconds "
                    "per page.",
                )

            # Deliberately unavailable rather than merely slow. A
            # 30-page upload would hold a request for ten minutes and
            # then be killed by the proxy, which reads as a broken
            # product rather than as the wrong machine for the job.
            return Availability(
                False,
                "ColPali needs a GPU. No CUDA or MPS device was found — set "
                "VISUAL_RAG_ALLOW_CPU_COLPALI=true to accept ~10-30s per "
                "page, or use the 'text-proxy' provider.",
            )

        return Availability(True, "Ready.")

    async def _load(self):
        if self._model is not None:
            return self._model, self._processor

        async with self._lock:
            # Re-checked inside the lock: several uploads can await the
            # first load at once, and loading a 6GB model twice is an
            # OOM rather than a slow path.
            if self._model is not None:
                return self._model, self._processor

            def _blocking():
                import torch
                from colpali_engine.models import ColPali, ColPaliProcessor

                if torch.cuda.is_available():
                    device = "cuda"
                    dtype = (
                        torch.bfloat16
                        if torch.cuda.is_bf16_supported()
                        else torch.float32
                    )
                elif torch.backends.mps.is_available():
                    device = "mps"
                    # MPS bfloat16 support is uneven across torch
                    # releases; float32 is the one that works everywhere.
                    dtype = torch.float32
                else:
                    device, dtype = "cpu", torch.float32

                app_logger.info(
                    f"visual rag: loading {MODEL_NAME} on {device} ({dtype})"
                )

                model = ColPali.from_pretrained(
                    MODEL_NAME, torch_dtype=dtype, device_map=device
                ).eval()

                return model, ColPaliProcessor.from_pretrained(MODEL_NAME)

            self._model, self._processor = await asyncio.to_thread(_blocking)

        return self._model, self._processor

    async def embed_pages(
        self,
        pages: list[RenderedPage],
        *,
        organization_id: uuid.UUID,
    ) -> list[np.ndarray]:
        model, processor = await self._load()

        def _blocking() -> list[np.ndarray]:
            import torch
            from PIL import Image

            images = [
                Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
                for page in pages
            ]

            results: list[np.ndarray] = []

            for start in range(0, len(images), BATCH_SIZE):
                batch = processor.process_images(images[start : start + BATCH_SIZE])
                batch = {key: value.to(model.device) for key, value in batch.items()}

                with torch.no_grad():
                    output = model(**batch)

                # (batch, patches, 128) -> one matrix per page, whole.
                # No mean over dim=1; that is the mistake this provider
                # exists to not make.
                for row in output:
                    results.append(normalize(row.to(torch.float32).cpu().numpy()))

            return results

        return await asyncio.to_thread(_blocking)

    async def embed_query(self, query: str) -> np.ndarray:
        model, processor = await self._load()

        def _blocking() -> np.ndarray:
            import torch

            batch = processor.process_queries([query])
            batch = {key: value.to(model.device) for key, value in batch.items()}

            with torch.no_grad():
                output = model(**batch)

            return normalize(output[0].to(torch.float32).cpu().numpy())

        return await asyncio.to_thread(_blocking)


colpali_visual_provider = ColPaliVisualProvider()
