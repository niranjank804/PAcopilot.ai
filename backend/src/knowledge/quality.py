"""Reject documents that would degrade retrieval instead of improving it.

A knowledge base is not a place where junk is merely inert. Every chunk
competes for the same `top_k` retrieval slots, and embeddings of
navigation chrome match essentially at random — so a scraped table of
contents actively displaces real content, and then gets cited as a
source. Nothing in the pipeline signalled this before: an upload of pure
page furniture reported "completed".

Each check below fires only on a document that is *mostly* junk, with
thresholds set well clear of anything a real reference or standards
document reaches. The failure message names the problem and what to do
about it, because "rejected" without a reason is its own support ticket.
"""

import re

# 'https://…' occupying an entire line — a table of contents, not prose.
_BARE_URL = re.compile(r"^\s*<?https?://\S+>?\s*$", re.IGNORECASE)

# The classic double-encoding signature: a UTF-8 lead byte decoded as
# Latin-1, giving 'Â®' for '®' or 'Ã©' for 'é'. Effectively never occurs
# in correctly decoded text.
_MOJIBAKE = re.compile(r"[ÂÃ][-¿]")

# A line carrying actual language: several words, ending like a sentence.
_PROSE_LINE = re.compile(r"\S+(\s+\S+){3,}.*[.!?:]\s*$")

MIN_LINES_TO_JUDGE = 12

URL_LINE_LIMIT = 0.45
DUPLICATE_LIMIT = 0.45
PROSE_FLOOR = 0.08
MOJIBAKE_LIMIT = 3


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def assess(text: str) -> list[str]:
    """Return reasons this document should not be indexed. Empty = fine."""

    lines = _lines(text)

    # Too small to judge statistically. A short document is not a junk
    # document, and rejecting one on a ratio computed from four lines
    # would be worse than admitting it.
    if len(lines) < MIN_LINES_TO_JUDGE:
        return []

    problems = []

    url_lines = sum(1 for line in lines if _BARE_URL.match(line))

    if url_lines / len(lines) > URL_LINE_LIMIT:
        problems.append(
            f"{round(url_lines / len(lines) * 100)}% of this document is bare "
            "URLs — it looks like a scraped table of contents rather than "
            "the pages themselves. Upload the content those links point to."
        )

    unique = len({line.casefold() for line in lines})

    if 1 - (unique / len(lines)) > DUPLICATE_LIMIT:
        problems.append(
            f"Only {unique} of {len(lines)} lines are distinct — the document "
            "is mostly repetition, which is typical of page furniture "
            "(navigation, footers) captured by a scraper."
        )

    prose_lines = sum(1 for line in lines if _PROSE_LINE.match(line))

    if prose_lines / len(lines) < PROSE_FLOOR:
        problems.append(
            "Almost none of this document is prose — it is mostly labels, "
            "identifiers, or markup. Retrieval has nothing meaningful to "
            "match against."
        )

    mojibake = len(_MOJIBAKE.findall(text))

    if mojibake > MOJIBAKE_LIMIT:
        problems.append(
            f"Text encoding is damaged ({mojibake} mis-decoded sequences, "
            "e.g. 'Â®' where '®' was meant). Re-export the source as UTF-8."
        )

    return problems
