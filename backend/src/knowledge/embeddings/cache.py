"""Cache for query embeddings.

Measured on a 219-chunk corpus, `search_knowledge_base` spent ~3,514ms
per call, of which roughly 490ms was local (406ms loading chunks, 81ms
scoring). The remaining ~3 seconds is the OpenAI embedding round trip.

So the retrieval code is not the bottleneck and optimising the cosine
loop would recover 81ms of 3,514. The win is not making the API call at
all, and repeat queries are common: a user rephrasing and retrying, an
agent calling the tool twice in one turn, several people asking the same
onboarding question.

Deliberately narrow:

* **Query embeddings only.** Document ingestion embeds each chunk once
  and never repeats it, so caching there would grow without ever hitting.
* **Keyed on (model, text).** Changing `EMBEDDING_MODEL` must not serve
  vectors from the old one — they are not comparable, and the resulting
  similarity scores would be quietly meaningless rather than obviously
  wrong.
* **Process-local and bounded.** No Redis to deploy. With
  `gunicorn --workers 2` each process keeps its own, which halves the
  hit rate and is a fine trade for zero infrastructure.
* **Not tenant-keyed on purpose.** An embedding is a pure function of
  text and model, carrying no organization data — the same sentence
  embeds identically for everyone. Adding organization_id to the key
  would only lower the hit rate. Note that this means the *text* of one
  tenant's query is briefly in memory shared with another's, which is
  already true of any process handling both.
"""

from collections import OrderedDict

# Entries are 1536 floats (~12KB as Python floats). 512 keeps the cache
# under ~10MB per process, which is affordable next to the model client
# and connection pool.
MAX_ENTRIES = 512

_cache: OrderedDict[tuple[str, str], list[float]] = OrderedDict()

_hits = 0
_misses = 0


def get(model: str, text: str) -> list[float] | None:
    global _hits, _misses

    key = (model, text)
    hit = _cache.get(key)

    if hit is None:
        _misses += 1

        return None

    # LRU: refresh position so a repeatedly-asked question is the last
    # thing evicted.
    _cache.move_to_end(key)
    _hits += 1

    return hit


def put(model: str, text: str, embedding: list[float]) -> None:
    key = (model, text)

    _cache[key] = embedding
    _cache.move_to_end(key)

    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def stats() -> dict:
    total = _hits + _misses

    return {
        "entries": len(_cache),
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 3) if total else 0.0,
    }


def clear() -> None:
    global _hits, _misses

    _cache.clear()
    _hits = 0
    _misses = 0
