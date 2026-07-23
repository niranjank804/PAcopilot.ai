from src.knowledge.retrieval import cosine_similarity


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_opposite_vectors_is_negative_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_cosine_similarity_zero_vector_is_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
