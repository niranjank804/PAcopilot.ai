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
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_coding_convention import TM1CodingConvention
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

    def summary(self) -> dict:
        return {
            "processes_parsed": self.parsed,
            "processes_failed": len(self.failed),
            "conventions_learned": self.stored_conventions,
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
    )


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
