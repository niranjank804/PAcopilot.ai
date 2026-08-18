"""Packing page embeddings.

The shape columns exist because a flat blob cannot describe itself, and
these tests are what keep a 1030x128 matrix from being read back as
128x1030 — which would not raise, it would silently transpose every
vector and rank pages by noise.
"""

import numpy as np
import pytest

from src.knowledge.visual.codec import EmbeddingShapeError, pack, unpack


def _normalised(count: int, dimensions: int, seed: int = 0) -> np.ndarray:
    generator = np.random.default_rng(seed)
    matrix = generator.standard_normal((count, dimensions)).astype(np.float32)

    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


class TestRoundTrip:

    def test_shape_survives(self):
        original = _normalised(1030, 128)

        blob, count, dimensions = pack(original)

        assert (count, dimensions) == (1030, 128)
        assert unpack(blob, count, dimensions).shape == (1030, 128)

    def test_values_survive_to_float16_precision(self):
        original = _normalised(64, 128)

        restored = unpack(*pack(original))

        # float16 carries ~3 decimal digits over the [-1, 1] range these
        # normalised vectors occupy.
        assert np.allclose(original, restored, atol=1e-3)

    def test_a_single_vector_round_trips(self):
        """The text-proxy provider's shape, 1x1536."""

        original = _normalised(1, 1536)

        assert unpack(*pack(original)).shape == (1, 1536)

    def test_ranking_is_unchanged_by_the_precision_loss(self):
        """The property that actually matters.

        Storage precision is only acceptable if it cannot reorder
        results. Scored against a real query, the float16 round trip
        must produce the same ranking as the float32 original.
        """

        from src.knowledge.visual.late_interaction import maxsim

        query = _normalised(20, 128, seed=99)
        pages = [_normalised(1030, 128, seed=index) for index in range(8)]

        exact = [maxsim(query, page) for page in pages]
        stored = [maxsim(query, unpack(*pack(page))) for page in pages]

        assert np.argsort(exact).tolist() == np.argsort(stored).tolist()

    def test_a_non_contiguous_matrix_round_trips(self):
        """A transposed or sliced array is not C-contiguous.

        `tobytes()` on one still produces bytes, so without an explicit
        copy this would round-trip into a scrambled matrix rather than
        an error.
        """

        original = _normalised(128, 64).T

        assert not original.flags["C_CONTIGUOUS"]
        assert np.allclose(unpack(*pack(original)), original, atol=1e-3)


class TestRejectedInput:

    def test_a_flat_vector_is_refused(self):
        # Ambiguous: 128 floats could be 1x128 or 128x1. The caller has
        # to say.
        with pytest.raises(EmbeddingShapeError):
            pack(np.zeros(128, dtype=np.float32))

    def test_a_truncated_blob_is_refused(self):
        blob, count, dimensions = pack(_normalised(10, 128))

        with pytest.raises(EmbeddingShapeError):
            unpack(blob[:-2], count, dimensions)

    def test_a_shape_that_does_not_match_the_blob_is_refused(self):
        """The realistic corruption: shape columns drifting from the blob.

        128x128 and 64x256 are both 16384 float16s, so a length check
        alone would accept the wrong one — this asserts the exact size
        is what is compared.
        """

        blob, _, _ = pack(_normalised(128, 128))

        with pytest.raises(EmbeddingShapeError):
            unpack(blob, 64, 128)

    def test_the_error_names_both_sizes(self):
        """So the log line is enough to diagnose it."""

        blob, count, dimensions = pack(_normalised(4, 8))

        with pytest.raises(EmbeddingShapeError) as exc_info:
            unpack(blob + b"\x00\x00", count, dimensions)

        assert "66" in str(exc_info.value)
        assert "64" in str(exc_info.value)


class TestComputeType:

    def test_unpacked_vectors_are_float32(self):
        """float16 accumulates visible error over a 128-term dot product.

        It is a storage format, not a compute format.
        """

        assert unpack(*pack(_normalised(4, 128))).dtype == np.float32
