"""Packing page embeddings for storage.

`knowledge_chunks` stores its vector as JSONB, which is fine for one
1536-float vector per chunk. It does not survive contact with late
interaction: ColPali emits ~1030 vectors *per page*, and JSONB stores
them as decimal text, so one 100-page document measures ~273MB — more
than half the free Postgres tier, for one file.

Measured, same vectors:

    JSONB text     2794 KB/page
    bytea float32   515 KB/page
    bytea float16   257 KB/page

float16 is the choice, and it is not a compromise. These vectors are
L2-normalised, so every component is in [-1, 1] where float16 carries
~3 decimal digits; the resulting MaxSim error measured 8.7e-06, which
is orders of magnitude below the gap between any two competing pages.
Spending 2x the storage to preserve digits the ranking cannot see would
be the compromise.

The shape is stored alongside rather than inferred, because a flat byte
string cannot say whether it is 1030x128 or 128x1030, and guessing wrong
transposes the whole matrix into confident nonsense.
"""

import numpy as np

_STORAGE_DTYPE = np.float16
# Everything above the storage boundary computes in float32: float16
# accumulates visible error in a dot product over hundreds of terms,
# and the memory saving only matters at rest.
_COMPUTE_DTYPE = np.float32


class EmbeddingShapeError(ValueError):
    ...


def pack(vectors: np.ndarray) -> tuple[bytes, int, int]:
    """(matrix) -> (bytes, vector_count, dimensions)."""

    if vectors.ndim != 2:
        raise EmbeddingShapeError(
            f"Expected a 2-D (vectors, dimensions) matrix, got shape {vectors.shape}."
        )

    count, dimensions = vectors.shape

    # C-contiguous is what `unpack` assumes when it reshapes. A sliced
    # or transposed array can be neither, and would round-trip into a
    # silently scrambled matrix rather than an error.
    return (
        np.ascontiguousarray(vectors, dtype=_STORAGE_DTYPE).tobytes(),
        count,
        dimensions,
    )


def unpack(data: bytes, vector_count: int, dimensions: int) -> np.ndarray:
    """(bytes, shape) -> float32 matrix."""

    expected = vector_count * dimensions * np.dtype(_STORAGE_DTYPE).itemsize

    if len(data) != expected:
        # Truncation is the realistic failure — a partial write, or a
        # shape column that drifted from its blob. Reshaping regardless
        # would either raise somewhere far away or, worse, succeed.
        raise EmbeddingShapeError(
            f"Embedding blob is {len(data)} bytes; "
            f"{vector_count}x{dimensions} needs {expected}."
        )

    return (
        np.frombuffer(data, dtype=_STORAGE_DTYPE)
        .reshape(vector_count, dimensions)
        .astype(_COMPUTE_DTYPE)
    )
