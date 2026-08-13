"""Query-embedding cache.

`search_knowledge_base` measured ~3,514ms per call, of which only ~490ms
was local (406ms loading chunks, 81ms scoring). The rest was the OpenAI
round trip, so the useful optimisation is not making the call twice for
the same question.
"""

import pytest

from src.knowledge.embeddings import cache


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


class TestBehaviour:

    def test_a_miss_then_a_hit(self):
        assert cache.get("model-a", "what is a feeder?") is None

        cache.put("model-a", "what is a feeder?", [0.1, 0.2])

        assert cache.get("model-a", "what is a feeder?") == [0.1, 0.2]

    def test_a_different_question_is_a_miss(self):
        cache.put("model-a", "question one", [0.1])

        assert cache.get("model-a", "question two") is None

    def test_changing_the_model_invalidates(self):
        """Vectors from different models are not comparable.

        Serving an old model's vector after EMBEDDING_MODEL changes would
        not error — it would silently produce meaningless similarity
        scores, which is far worse than a cache miss.
        """

        cache.put("text-embedding-3-small", "q", [0.1])

        assert cache.get("text-embedding-3-large", "q") is None

    def test_stats_track_hits_and_misses(self):
        cache.get("m", "a")
        cache.put("m", "a", [0.1])
        cache.get("m", "a")

        stats = cache.stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["entries"] == 1


class TestBoundedness:

    def test_the_cache_does_not_grow_without_limit(self):
        # Each entry is ~12KB of floats; unbounded growth in a
        # long-lived process is a slow memory leak.
        for i in range(cache.MAX_ENTRIES + 50):
            cache.put("m", f"question {i}", [0.1])

        assert len(cache._cache) == cache.MAX_ENTRIES

    def test_the_least_recently_used_entry_is_evicted(self):
        for i in range(cache.MAX_ENTRIES):
            cache.put("m", f"q{i}", [float(i)])

        # Touch the oldest so it is no longer least-recently-used.
        assert cache.get("m", "q0") is not None

        cache.put("m", "brand new", [0.9])

        # q0 survived because it was used; q1 was evicted instead.
        assert cache.get("m", "q0") is not None
        assert cache.get("m", "q1") is None

    def test_repeating_a_question_keeps_it_alive(self):
        cache.put("m", "popular", [0.5])

        for i in range(cache.MAX_ENTRIES):
            cache.put("m", f"filler {i}", [0.1])
            cache.get("m", "popular")

        assert cache.get("m", "popular") == [0.5]


class TestWiring:

    def test_only_the_query_path_uses_the_cache(self):
        """Ingestion must not be cached.

        upload_document embeds each chunk exactly once, so caching there
        would fill the cache with entries that never hit and evict the
        queries that do.
        """

        import inspect

        from src.knowledge import service

        source = inspect.getsource(service)

        # Present on the search path...
        assert "embedding_cache.get(" in source
        assert "embedding_cache.put(" in source

        # ...and absent from the ingestion function body. Scoped to the
        # function rather than "everything before search", which would
        # include the import block and always match.
        ingest = inspect.getsource(service.KnowledgeService.upload_document)

        assert "embedding_cache" not in ingest, (
            "document ingestion should not populate the query cache"
        )
