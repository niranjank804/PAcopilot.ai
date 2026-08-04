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


class _Budget:
    """Expansion allowance for one request, shared across every uploaded part.

    Scoping this per archive rather than per request let a caller send twenty
    small zips and expand each to the full limit — twenty times the memory the
    limit was written to cap.
    """

    def __init__(self) -> None:
        self.bytes_left = MAX_EXPANDED_BYTES
        self.files_left = MAX_FILES

    def take(self, size: int) -> None:
        self.bytes_left -= size

        if self.bytes_left < 0:
            raise ValidationException(
                "This upload expands beyond the 100MB limit."
            )

    def take_file(self) -> None:
        self.files_left -= 1

        if self.files_left < 0:
            raise ValidationException(
                f"This upload contains more than {MAX_FILES} files."
            )


def _expand(
    filename: str, raw: bytes, budget: _Budget
) -> tuple[dict[str, str], list[RejectedFileResponse]]:
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
        budget.take_file()
        return {filename: _decode(raw)}, []

    files: dict[str, str] = {}

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return {}, [
            RejectedFileResponse(
                filename=filename, reason="Archive is corrupt or unreadable."
            )
        ]

    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue

            name = member.filename.rsplit("/", 1)[-1]

            if not name.lower().endswith(TEXT_SUFFIXES):
                continue

            budget.take_file()

            try:
                with archive.open(member) as handle:
                    # Read at most what the budget still allows, then charge
                    # what was actually read — a zip header can claim anything,
                    # so the declared size cannot be the control.
                    payload = handle.read(max(budget.bytes_left, 0) + 1)
            except (zipfile.BadZipFile, EOFError, RuntimeError) as exc:
                # A corrupt member, a CRC mismatch, or an encrypted archive.
                # One bad member should cost that member, not the upload.
                rejected.append(
                    RejectedFileResponse(
                        filename=name,
                        reason=f"Archive member could not be read: {exc}",
                    )
                )
                continue

            budget.take(len(payload))
            files[name] = _decode(payload)

    if not files and not rejected:
        rejected.append(
            RejectedFileResponse(
                filename=filename,
                reason="Archive contained no .pro or .txt exports.",
            )
        )

    return files, rejected


def _nothing_found(rejected: list[RejectedFileResponse]) -> str:
    """Explain why an upload yielded nothing, using the reasons already known.

    "No exports found" alone leaves the uploader guessing whether the file was
    the wrong type, corrupt, or simply empty — when the per-file reason was
    collected and then thrown away.
    """

    base = (
        "No TurboIntegrator exports found. Upload .pro files, or a zip "
        "containing them."
    )

    if not rejected:
        return base

    detail = "; ".join(f"{r.filename}: {r.reason}" for r in rejected[:5])
    return f"{base} Rejected — {detail}"


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
    budget = _Budget()
    total = 0

    for upload in files:
        raw = await upload.read()
        total += len(raw)

        if total > MAX_UPLOAD_BYTES:
            raise ValidationException("Upload exceeds the 25MB limit.")

        expanded, skipped = _expand(upload.filename or "untitled", raw, budget)
        corpus.update(expanded)
        rejected.extend(skipped)

    if not corpus:
        raise ValidationException(_nothing_found(rejected))

    result = await learn_from_processes(
        db, organization_id=current_user.organization_id, files=corpus
    )

    rejected.extend(
        RejectedFileResponse(filename=name, reason=reason)
        for name, reason in result.failed
    )

    note = None

    if not result.replaced_existing:
        note = (
            f"This corpus of {result.parsed} process(es) produced no convention "
            f"confident enough to become a standard, so the "
            f"{result.previous_conventions} already learned for your "
            "organization were kept. Upload a larger corpus — roughly eight "
            "processes before a unanimous practice reaches confidence — to "
            "replace them."
        )

    return ApiResponse(
        success=True,
        data=LearningRunResponse(
            processes_parsed=result.parsed,
            processes_failed=len(result.failed),
            conventions_learned=result.stored_conventions,
            replaced_existing=result.replaced_existing,
            note=note,
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
                1 for r in result.records if r.has_stored_credentials
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
    rejected: list[RejectedFileResponse] = []
    budget = _Budget()
    total = 0

    for upload in files:
        raw = await upload.read()
        total += len(raw)

        if total > MAX_UPLOAD_BYTES:
            raise ValidationException("Upload exceeds the 25MB limit.")

        expanded, skipped = _expand(upload.filename or "untitled", raw, budget)
        corpus.update(expanded)
        rejected.extend(skipped)

    if not corpus:
        raise ValidationException(_nothing_found(rejected))

    records, _ = parse_corpus(corpus)

    return ApiResponse(
        success=True,
        data=StandardsReportResponse(
            markdown=render_markdown(build_report(records))
        ),
    )
