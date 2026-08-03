import io
import zipfile

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.core.exceptions import ValidationException
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.learning import (
    ConventionResponse,
    LearningRunResponse,
    PatternCountResponse,
    RejectedFileResponse,
    StandardsReportResponse,
    StandardsResponse,
)
from src.schemas.response import ApiResponse
from src.tm1.ti.learning import get_conventions, learn_from_processes, parse_corpus
from src.tm1.ti.patterns import PATTERNS
from src.tm1.ti.report import build_report, render_markdown

router = APIRouter(
    prefix="/learning",
    tags=["Learning"],
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# A zip declaring far more than a large TM1 server holds is not a corpus.
MAX_FILES = 2000
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
TEXT_SUFFIXES = (".pro", ".txt")

_PATTERNS_BY_KEY = {p.key: p for p in PATTERNS}


def _decode(raw: bytes) -> str:
    # TM1 writes these with a BOM; utf-8-sig strips it when present and is a
    # plain utf-8 decode when it is not. errors="replace" keeps one bad byte
    # from costing the whole process.
    return raw.decode("utf-8-sig", errors="replace")


def _expand(filename: str, raw: bytes) -> tuple[dict[str, str], list[RejectedFileResponse]]:
    """Turn one upload into `{name: text}`, expanding a zip if that is what it is."""

    rejected: list[RejectedFileResponse] = []

    if not zipfile.is_zipfile(io.BytesIO(raw)):
        if not filename.lower().endswith(TEXT_SUFFIXES):
            return {}, [
                RejectedFileResponse(
                    filename=filename,
                    reason="Not a .pro or .txt export, and not a zip archive.",
                )
            ]
        return {filename: _decode(raw)}, []

    files: dict[str, str] = {}
    expanded = 0

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]

        if len(members) > MAX_FILES:
            raise ValidationException(
                f"Archive contains {len(members)} files; the limit is {MAX_FILES}."
            )

        for member in members:
            name = member.filename.rsplit("/", 1)[-1]

            if not name.lower().endswith(TEXT_SUFFIXES):
                continue

            # Trust the declared size only as a first filter, then measure what
            # was actually read — a zip header can claim anything.
            expanded += member.file_size

            if expanded > MAX_EXPANDED_BYTES:
                raise ValidationException(
                    "Archive expands beyond the 100MB limit."
                )

            with archive.open(member) as handle:
                files[name] = _decode(handle.read(MAX_EXPANDED_BYTES + 1))

    if not files:
        rejected.append(
            RejectedFileResponse(
                filename=filename,
                reason="Archive contained no .pro or .txt exports.",
            )
        )

    return files, rejected


@router.post(
    "/corpus",
    response_model=ApiResponse[LearningRunResponse],
    status_code=201,
)
async def learn_corpus(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.write")),
):
    """Learn this organization's coding conventions from exported TI processes.

    Accepts individual `.pro` exports or a zip of them. Replaces the
    organization's previously learned conventions rather than merging: they
    describe a corpus, and letting a codebase that has since changed keep
    voting on how new code should look is how stale standards get enforced.
    """

    corpus: dict[str, str] = {}
    rejected: list[RejectedFileResponse] = []
    total = 0

    for upload in files:
        raw = await upload.read()
        total += len(raw)

        if total > MAX_UPLOAD_BYTES:
            raise ValidationException("Upload exceeds the 25MB limit.")

        expanded, skipped = _expand(upload.filename or "untitled", raw)
        corpus.update(expanded)
        rejected.extend(skipped)

    if not corpus:
        raise ValidationException(
            "No TurboIntegrator exports found. Upload .pro files, or a zip "
            "containing them."
        )

    result = await learn_from_processes(
        db, organization_id=current_user.organization_id, files=corpus
    )

    rejected.extend(
        RejectedFileResponse(filename=name, reason=reason)
        for name, reason in result.failed
    )

    records, _ = parse_corpus(corpus)

    return ApiResponse(
        success=True,
        data=LearningRunResponse(
            processes_parsed=result.parsed,
            processes_failed=len(result.failed),
            conventions_learned=result.stored_conventions,
            patterns=[
                PatternCountResponse(
                    key=key,
                    name=_PATTERNS_BY_KEY[key].name,
                    description=_PATTERNS_BY_KEY[key].description,
                    process_count=len(names),
                )
                for key, names in sorted(result.patterns.items())
                if key in _PATTERNS_BY_KEY
            ],
            rejected=rejected,
            files_with_stored_credentials=sum(
                1 for r in records if r.has_stored_credentials
            ),
        ),
    )


@router.get(
    "/standards",
    response_model=ApiResponse[StandardsResponse],
)
async def read_standards(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    """The conventions learned for this organization, strongest evidence first."""

    conventions = await get_conventions(
        db, organization_id=current_user.organization_id
    )

    return ApiResponse(
        success=True,
        data=StandardsResponse(
            process_count=max((c.sample for c in conventions), default=0),
            conventions=[
                ConventionResponse(
                    key=c.convention_key,
                    statement=c.statement,
                    confidence=round(c.confidence, 3),
                    support=c.support,
                    sample=c.sample,
                    examples=c.examples,
                    counter_examples=c.counter_examples,
                )
                for c in conventions
            ],
        ),
    )


@router.post(
    "/report",
    response_model=ApiResponse[StandardsReportResponse],
)
async def standards_report(
    files: list[UploadFile] = File(...),
    current_user: UserResponse = Depends(require_permission("tm1.read")),
):
    """Render the standards report for a corpus without storing anything.

    Separate from /corpus so a lead can review what would be learned — and
    what the codebase does *not* do — before it becomes the standard that
    generated code is held to.
    """

    corpus: dict[str, str] = {}
    total = 0

    for upload in files:
        raw = await upload.read()
        total += len(raw)

        if total > MAX_UPLOAD_BYTES:
            raise ValidationException("Upload exceeds the 25MB limit.")

        expanded, _ = _expand(upload.filename or "untitled", raw)
        corpus.update(expanded)

    if not corpus:
        raise ValidationException(
            "No TurboIntegrator exports found. Upload .pro files, or a zip "
            "containing them."
        )

    records, _ = parse_corpus(corpus)

    return ApiResponse(
        success=True,
        data=StandardsReportResponse(
            markdown=render_markdown(build_report(records))
        ),
    )
