"""MaxSim scoring — the mechanism ColPali actually retrieves with.

A conventional embedding model compresses a page into one vector, so
"what drove the Q3 EMEA variance?" must match a whole page at once.
ColPali instead emits one vector per image patch (~1030 for a page) and
one per query token, then scores by late interaction:

    score(q, d) = Σ over query tokens i  ·  max over patches j  ( q_i · d_j )

Each query token independently finds the region of the page that answers
it. "EMEA" can match a row label in a corner while "Q3" matches a column
header elsewhere, and the page still scores highly — which single-vector
retrieval cannot express, because averaging the page into one point
throws away *where* things are.

This is worth stating because it is the step most implementations drop.
Mean-pooling the patch vectors into one 128-d vector and running ordinary
cosine (as the reference implementation for this feature does, in both
ingestion and query) is not a lighter ColPali; it discards the only thing
ColPali adds, leaving a mediocre single-vector retriever running on a 3B
parameter model. `test_late_interaction.py` pins the difference with a
case that mean-pooling provably gets wrong.
"""

import numpy as np

# Per-token mean rather than the raw sum. The sum grows with query
# length, so a threshold tuned on a three-word question would silently
# admit everything for a twenty-word one, and scores from different
# queries could not be compared or shown in a UI. Dividing by the query
# token count puts every score in the same [-1, 1] range as the cosine
# similarity used by text retrieval.
def maxsim(query_vectors: np.ndarray, page_vectors: np.ndarray) -> float:
    """Late-interaction score between one query and one page.

    Both arrays are (n_vectors, dim) and assumed L2-normalised, which
    makes the dot product a cosine.
    """

    if query_vectors.size == 0 or page_vectors.size == 0:
        return 0.0

    # (n_query, n_patches) — every query token against every patch.
    similarity = query_vectors @ page_vectors.T

    return float(similarity.max(axis=1).mean())


def normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalise each row, leaving zero rows alone.

    ColPali already emits normalised vectors, but a provider is an
    interface others can implement and an un-normalised one would make
    every score meaningless rather than merely wrong — the magnitudes
    would dominate the ranking.
    """

    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)

    return vectors / np.where(norms == 0, 1.0, norms)


def as_array(vectors: list[list[float]]) -> np.ndarray:
    """JSON-decoded embeddings to a normalised float32 matrix.

    float32 halves the memory of a scan versus float64 and matches the
    precision the model emitted; float64 would be inventing significance
    that was never there.
    """

    array = np.asarray(vectors, dtype=np.float32)

    if array.ndim == 1:
        # A single-vector provider is a legitimate implementation of the
        # interface — it is simply late interaction with one token, for
        # which MaxSim reduces exactly to cosine similarity. Reshaping
        # here means the scoring path does not need to know which kind
        # of provider produced the embedding.
        array = array.reshape(1, -1)

    return normalize(array)
