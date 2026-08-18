"""Late interaction, and why mean-pooling is not a cheaper version of it.

The headline test is `test_mean_pooling_ranks_the_wrong_page`, which is
the reason this module exists rather than a call to `cosine_similarity`.
"""

import numpy as np

from src.knowledge.visual.late_interaction import as_array, maxsim, normalize


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


class TestMaxSim:

    def test_identical_content_scores_one(self):
        vectors = as_array([[1.0, 0.0, 0.0, 0.0]])

        assert maxsim(vectors, vectors) == 1.0

    def test_each_query_token_scores_its_own_best_patch(self):
        """The property single-vector retrieval cannot express.

        Two query terms answered by two *different* regions of a page
        still score perfectly, because each token maximises
        independently.
        """

        query = as_array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        page = as_array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])

        assert maxsim(query, page) == 1.0

    def test_unrelated_content_scores_near_zero(self):
        query = as_array([[1.0, 0.0, 0.0, 0.0]])
        page = as_array([[0.0, 0.0, 1.0, 0.0]])

        assert maxsim(query, page) == 0.0

    def test_the_score_does_not_grow_with_query_length(self):
        """Otherwise no fixed relevance floor could exist.

        The raw MaxSim sum scales with token count, so a threshold tuned
        on a short question would admit everything for a long one. The
        per-token mean keeps every score comparable.
        """

        page = as_array([[1.0, 0.0, 0.0, 0.0]])

        short = maxsim(as_array([[1.0, 0.0, 0.0, 0.0]]), page)
        long = maxsim(as_array([[1.0, 0.0, 0.0, 0.0]] * 20), page)

        assert short == long

    def test_empty_input_is_zero_not_an_error(self):
        vectors = as_array([[1.0, 0.0, 0.0, 0.0]])
        empty = np.zeros((0, 4), dtype=np.float32)

        assert maxsim(empty, vectors) == 0.0
        assert maxsim(vectors, empty) == 0.0


class TestWhyNotMeanPooling:

    def test_mean_pooling_ranks_the_wrong_page(self):
        """The concrete failure this whole module exists to avoid.

        Page A genuinely answers both halves of the query — one patch
        matches each — but it also carries a third, unrelated region, as
        any real report page does. Page B is a near-empty page whose
        single patch sits at the *average* of the two query directions
        without actually containing either.

        Averaging a page into one vector lets B's lack of content beat
        A's relevance: A's mean is dragged toward its third region,
        while B's mean is by construction pointed straight at the query.
        MaxSim is unaffected, because it never averages — it asks
        whether some patch answers each token.

        This is not a contrived edge case. It is the systematic bias of
        mean-pooling against information-dense pages, which are exactly
        the pages a variance question needs to find.
        """

        query = as_array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])

        page_a = as_array([
            [1.0, 0.0, 0.0, 0.0],   # answers token 1
            [0.0, 1.0, 0.0, 0.0],   # answers token 2
            [0.0, 0.0, 1.0, 0.0],   # unrelated third region
        ])
        page_b = as_array([[1.0, 1.0, 0.0, 0.0]])  # the average, answering neither

        # Late interaction: A is the better page, decisively.
        assert maxsim(query, page_a) == 1.0
        assert maxsim(query, page_b) < 0.75
        assert maxsim(query, page_a) > maxsim(query, page_b)

        # Mean-pooled cosine, which is what the reference implementation
        # computes: the ranking inverts.
        pooled_query = query.mean(axis=0)
        pooled_a = page_a.mean(axis=0)
        pooled_b = page_b.mean(axis=0)

        assert cosine(pooled_query, pooled_b) > cosine(pooled_query, pooled_a)


class TestNormalisation:

    def test_rows_become_unit_length(self):
        result = normalize(np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32))

        assert np.allclose(np.linalg.norm(result, axis=1), 1.0)

    def test_a_zero_vector_does_not_divide_by_zero(self):
        result = normalize(np.array([[0.0, 0.0]], dtype=np.float32))

        assert not np.isnan(result).any()

    def test_magnitude_cannot_dominate_ranking(self):
        """An un-normalised provider would rank by vector length.

        Same direction, ten times the magnitude, must score the same.
        """

        query = as_array([[1.0, 0.0]])

        assert maxsim(query, as_array([[1.0, 0.0]])) == maxsim(
            query, as_array([[10.0, 0.0]])
        )


class TestSingleVectorProviders:

    def test_a_flat_vector_is_treated_as_one_token(self):
        """MaxSim with one query token and one patch *is* cosine.

        This is what lets a single-vector provider share the scoring
        path rather than needing a second one.
        """

        flat = as_array([0.6, 0.8])

        assert flat.shape == (1, 2)
        assert maxsim(flat, flat) == 1.0
