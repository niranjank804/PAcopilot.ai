"""Turn a set of exported TI processes into stored, citable conventions.

This is the write side of the learning loop. It parses an upload, measures the
organization's conventions, and persists them so that later code generation is
grounded in what this team actually does rather than in generic TM1 advice.

Learning is per-organization and replaces the previous measurement wholesale.
Conventions are a snapshot of a corpus, not an accumulating log: merging a new
upload into old counts would let a codebase that has since changed keep voting
on how new code should look.
"""

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_coding_convention import TM1CodingConvention
from src.database.models.tm1_process import TM1Process, TM1ProcessPattern
from src.tm1.ti.conventions import CodingDNA, infer_conventions
from src.tm1.ti.parser import ProcessRecord, parse_process
from src.tm1.ti.patterns import classify

logger = logging.getLogger(__name__)

# Below this, an observation is a coincidence rather than a convention. A rule
# held by a third of a corpus is not a house style, and presenting it as one
# would have the assistant enforce noise.
MINIMUM_CONFIDENCE = 0.6


@dataclass
class LearningResult:
    parsed: int
    failed: list[tuple[str, str]]
    dna: CodingDNA
    patterns: dict[str, list[str]]
    stored_conventions: int
    records: list[ProcessRecord] = field(default_factory=list)
    # False when a corpus produced nothing and the organization's existing
    # standards were therefore left in place.
    replaced_existing: bool = True
    previous_conventions: int = 0

    def summary(self) -> dict:
        return {
            "processes_parsed": self.parsed,
            "processes_failed": len(self.failed),
            "conventions_learned": self.stored_conventions,
            "replaced_existing": self.replaced_existing,
            "patterns_recognised": {
                key: len(names) for key, names in sorted(self.patterns.items())
            },
        }


def parse_corpus(files: dict[str, str]) -> tuple[list[ProcessRecord], list[tuple[str, str]]]:
    """Parse `{filename: contents}`, isolating failures to a single file.

    One malformed export must not cost the other sixty-three: an upload is
    usually a whole-server dump, and rejecting the batch would mean a team
    learns nothing because one process was truncated.
    """

    records: list[ProcessRecord] = []
    failed: list[tuple[str, str]] = []

    for filename, contents in files.items():
        try:
            records.append(parse_process(contents, source_file=filename))
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            logger.warning("Failed to parse TI export %s: %s", filename, exc)
            failed.append((filename, str(exc)))

    return records, failed


async def learn_from_processes(
    db: AsyncSession,
    *,
    organization_id,
    files: dict[str, str],
    minimum_confidence: float = MINIMUM_CONFIDENCE,
) -> LearningResult:
    """Parse an upload, measure conventions, and persist them for the org."""

    records, failed = parse_corpus(files)
    dna = infer_conventions(records)

    patterns: dict[str, list[str]] = {}
    for record in records:
        for match in classify(record):
            patterns.setdefault(match.key, []).append(record.name)

    keepers = [c for c in dna.conventions if c.confidence >= minimum_confidence]
    existing = await get_conventions(db, organization_id=organization_id)

    # Replacing a learned standard with a better measurement is the point.
    # Replacing it with *nothing* is destruction: a corpus too small to reach
    # confidence — someone uploading three files to see what happens — would
    # otherwise silently wipe standards measured from a whole server, and the
    # agents would go back to generic TM1 style with no one told why.
    if not keepers and existing:
        logger.info(
            "Corpus of %d processes produced no conventions; keeping the "
            "%d already learned for organization %s.",
            len(records),
            len(existing),
            organization_id,
        )
        return LearningResult(
            parsed=len(records),
            failed=failed,
            dna=dna,
            patterns=patterns,
            stored_conventions=len(existing),
            records=records,
            replaced_existing=False,
            previous_conventions=len(existing),
        )

    await _persist_processes(db, organization_id=organization_id, records=records)

    await db.execute(
        delete(TM1CodingConvention).where(
            TM1CodingConvention.organization_id == organization_id
        )
    )

    for convention in keepers:
        db.add(
            TM1CodingConvention(
                organization_id=organization_id,
                convention_key=convention.key,
                statement=convention.statement,
                confidence=convention.confidence,
                support=convention.support,
                sample=convention.sample,
                examples=convention.examples[:10],
                counter_examples=convention.counter_examples[:10],
            )
        )

    await db.flush()

    return LearningResult(
        parsed=len(records),
        failed=failed,
        dna=dna,
        patterns=patterns,
        stored_conventions=len(keepers),
        records=records,
        replaced_existing=True,
        previous_conventions=len(existing),
    )


async def _persist_processes(
    db: AsyncSession, *, organization_id, records: Sequence[ProcessRecord]
) -> None:
    """Replace the stored structure for an organization's processes.

    Like the conventions, this is a snapshot of one corpus rather than an
    accumulating history: leaving behind processes that no longer exist on the
    server would let a deleted process keep appearing in dependency answers.

    Source code is not stored — see the model docstring.
    """

    await db.execute(
        delete(TM1Process).where(TM1Process.organization_id == organization_id)
    )
    # Pattern rows cascade from the process rows, but the delete above is
    # issued as bulk SQL, so flush before inserting to guarantee ordering.
    await db.flush()

    seen: set[str] = set()

    for record in records:
        if not record.name or record.name in seen:
            # The unique constraint is (organization_id, name). Two exports
            # can carry the same process name — a re-download, or two folders
            # merged — and one collision must not fail the whole upload.
            continue

        seen.add(record.name)

        process = TM1Process(
            organization_id=organization_id,
            name=record.name,
            source_file=record.source_file[:255],
            datasource_type=record.datasource_type,
            header_comment=record.header_comment,
            has_stored_credentials=record.has_stored_credentials,
            line_counts=record.line_counts,
            parameters=record.parameters,
            objects=[asdict(o) for o in record.objects],
            functions_used=record.functions_used,
            process_calls=sorted(record.processes_called),
            object_count=len(record.objects),
        )
        db.add(process)
        await db.flush()

        for match in classify(record):
            db.add(
                TM1ProcessPattern(
                    organization_id=organization_id,
                    process_id=process.id,
                    pattern_key=match.key,
                    score=match.score,
                    evidence=match.evidence,
                )
            )

    await db.flush()


async def get_conventions(
    db: AsyncSession, *, organization_id
) -> list[TM1CodingConvention]:
    """Learned conventions for an organization, strongest evidence first."""

    result = await db.execute(
        select(TM1CodingConvention)
        .where(TM1CodingConvention.organization_id == organization_id)
        .order_by(TM1CodingConvention.confidence.desc())
    )

    return list(result.scalars().all())
