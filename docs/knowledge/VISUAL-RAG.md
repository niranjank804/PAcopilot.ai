# Visual RAG (ColPali)

Retrieval over page *images* rather than extracted text.

## Why

`pdf_loader` reads a PDF with pypdf and returns a flat string. For prose
that is the right answer. For the documents this product deals with it
throws away the thing that carried the meaning.

A Planning Analytics variance pack is mostly tables, pivot exports and
charts. Extracted from a PDF, a table becomes an unordered column of
numbers with the row and column headings that gave them meaning
discarded — so "EMEA, Q3, unfavourable, 1.2m" arrives as four numbers in
no particular relation to each other. A chart extracts to nothing at all,
or to its axis labels.

A page image keeps the layout. Both ColPali and Claude read layout
directly.

## The pipeline

```
upload ─► rasterize ─► store image ─► embed page ─► visual_pages row
query  ─► embed ─────► MaxSim over pages ─► top-k page images ─► Claude
```

The last arrow is the point. What is handed to the model is the
*rendered page*, not a serialisation of it.

| Stage | Module |
|---|---|
| PDF → JPEG pages | [`visual/rasterize.py`](../../backend/src/knowledge/visual/rasterize.py) |
| MaxSim scoring | [`visual/late_interaction.py`](../../backend/src/knowledge/visual/late_interaction.py) |
| Embedding storage | [`visual/codec.py`](../../backend/src/knowledge/visual/codec.py) |
| Providers | [`visual/providers/`](../../backend/src/knowledge/visual/providers/) |
| Orchestration | [`visual/service.py`](../../backend/src/knowledge/visual/service.py) |

## Late interaction, and the mistake to avoid

ColPali emits one vector per image patch (~1030 per page) and one per
query token. It scores by late interaction:

```
score(q, d) = Σ over query tokens i  ·  max over patches j  ( q_i · d_j )
```

Each query token independently finds the region of the page that answers
it. "EMEA" can match a row label in one corner while "Q3" matches a
column header elsewhere, and the page still scores highly.

**Mean-pooling the patch vectors into one vector and running ordinary
cosine is not a lighter ColPali.** It discards the only thing ColPali
adds. This is worth stating because most published implementations do
it — including the one this feature was modelled on, which calls
`.mean(dim=1)` in both ingestion and query and then runs L2 distance in
pgvector. What remains is a mediocre single-vector retriever running on
a 3B-parameter model.

`test_late_interaction.py::test_mean_pooling_ranks_the_wrong_page` pins
a case where it provably inverts the ranking: a page that genuinely
answers both halves of a query loses to a near-empty page whose single
patch happens to sit at the average of the two query directions.
Averaging drags a dense page's vector toward whatever else is on it, so
mean-pooling is systematically biased *against* information-rich pages —
exactly the pages a variance question needs.

## Providers

Selected with `VISUAL_RAG_PROVIDER`.

### `text-proxy` (default, runs anywhere)

Embeds each page's extracted text with the existing OpenAI text
embedding provider; one vector per page, so MaxSim reduces exactly to
cosine.

Honestly, this is half of visual RAG — and it is the half that runs on
the deployment this product actually has:

- **What it buys.** Retrieval picks the page by its text, but what is
  sent to Claude is the *rendered page*. A question whose answer lives
  in a chart is answered correctly whenever the surrounding text is
  enough to find the page.
- **What it does not buy.** Finding a page whose answer is *only*
  visual — an unlabelled trend line, a figure with no caption.

A page yielding under 40 characters of text is stored without an
embedding. Its image is kept (ColPali could index it later) but it is
never retrieved, because embedding a handful of characters would place
it arbitrarily in the vector space and let it surface for unrelated
queries.

### `colpali` (needs a GPU)

`vidore/colpali-v1.3`, full multi-vector, late interaction intact.

**This cannot run on the free deployment.** The weights are ~6GB in
bfloat16; a free Render container has 512MB and no GPU. `availability()`
reports that as a sentence rather than letting the process be OOM-killed
mid-request, and `torch`/`colpali_engine` are imported inside methods so
that a container without them still boots.

To use it on a machine with a GPU:

```bash
pip install torch colpali-engine==0.3.4
```

```bash
VISUAL_RAG_PROVIDER=colpali
```

Then re-index: pages carry the provider that embedded them, and
retrieval filters on it, so existing `text-proxy` pages will not be
ranked against ColPali ones. Vectors from different providers occupy
different spaces — comparing them ranks by numbers that have no
relationship.

CPU inference is ~10-30s per page and is refused unless
`VISUAL_RAG_ALLOW_CPU_COLPALI=true`. A 30-page upload would otherwise
hold a request for ten minutes and then be killed by the proxy, which
reads as a broken product rather than as the wrong machine for the job.

> The natural home for ColPali in this codebase is the **report worker
> plane** — it already has job claiming, leases and heartbeats, and a
> GPU-equipped worker would be a machine that can hold the model. That
> is not built; the provider interface is what makes it a contained
> change when it is.

## Storage

Page images go through `StorageBackend`, so they land in S3 when
`S3_BUCKET` is set and in Postgres otherwise, and the S3 backend's
tenant-prefix check applies to them unchanged.

**On Render, configure S3 before relying on this.** Without AWS
credentials the object store write fails, visual indexing is skipped
(non-fatally, see below) and nothing is retrievable visually. With
Postgres storage instead, a 100-page document is ~20MB of images in a
500MB free tier.

Embeddings are float16 `bytea`, not JSONB. Measured on real ColPali
output:

| Encoding | Per page | 100-page document |
|---|---|---|
| JSONB (what `knowledge_chunks` uses) | 2794 KB | 273 MB |
| bytea float32 | 515 KB | 50 MB |
| **bytea float16** | **257 KB** | **25 MB** |

float16 is not a compromise: these vectors are L2-normalised, so every
component sits in [-1, 1] where float16 carries ~3 decimal digits. The
measured MaxSim error is 8.7e-06, orders of magnitude below the gap
between competing pages, and `test_codec.py` asserts the ranking is
identical after a round trip.

The shape is stored in its own columns because a flat blob cannot say
whether it is 1030x128 or 128x1030, and guessing wrong transposes the
matrix into confident nonsense rather than raising.

## Degradation

Visual indexing is **additive and non-fatal**. Text indexing is what the
product has always relied on, so if rasterizing or embedding fails — no
GPU, an image-only PDF, an unreachable bucket — the document is still
searchable by text. The reason is recorded on
`knowledge_documents.visual_index_error`, kept separate from
`error_message` because the document has not failed.

Because that degradation is silent by design, `GET
/knowledge/visual/status` exists to make it visible. Without it there is
no way to tell "no relevant pages" apart from "this never worked here".

## API

| Endpoint | Purpose |
|---|---|
| `GET /knowledge/visual/status` | Whether visual search can run, and why not |
| `GET /knowledge/pages/{id}/image` | The rendered page behind a citation |

`POST /knowledge/ask` gains `page_citations`, listing the pages actually
attached to the call. Deliberately separate from `citations`: a chunk
citation says a passage of text was in the prompt, a page citation says
a picture was.

The image endpoint checks tenancy twice — the row against the caller's
organization, and the key prefix inside the storage backend — because a
citation id is exactly the kind of value that ends up in a URL, and one
check is one forgotten `if` away from serving another tenant's page. It
answers 404 rather than 403 for another organization's page, since
whether an id exists is itself information.

## Settings

| Setting | Default | Notes |
|---|---|---|
| `VISUAL_RAG_ENABLED` | `true` | |
| `VISUAL_RAG_PROVIDER` | `text-proxy` | or `colpali` |
| `VISUAL_RAG_RENDER_DPI` | `150` | below ~110, small figures break up |
| `VISUAL_RAG_MAX_IMAGE_DIMENSION` | `1400` | Claude downsamples above ~1568 anyway |
| `VISUAL_RAG_MAX_PAGES` | `100` | bounds what one upload can cost |
| `VISUAL_RAG_TOP_K` | `3` | pages attached per answer |
| `VISUAL_RAG_MINIMUM_SCORE` | `0.25` | relevance floor |
| `VISUAL_RAG_ALLOW_CPU_COLPALI` | `false` | |

## Known limits

- **Retrieval is an exact scan**, linear in page count. Honest but
  bounded: the existing text retrieval already scans the same way, in
  slower pure Python. At tens of thousands of pages per tenant this is
  the thing to replace, with pgvector multi-vector support or a
  two-stage candidate-then-rerank. The service interface does not change
  when it is.
- **PDF only.** DOCX and XLSX are text-indexed as before. Rendering them
  means an office runtime, which is a much larger dependency than
  pdfium.
- **ColPali is unvalidated against real PAfE exports.** The pipeline is
  tested end to end with generated PDFs; no accuracy claim is made about
  ColPali on Planning Analytics output until it has been run on some.
