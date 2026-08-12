"""An isolated, disposable directory for one execution.

Path safety here is structural rather than defensive: the workbook is
written to a filename derived from the execution's UUID, so the
server-supplied filename never becomes a path component at all. There is
no traversal sequence that survives, because the attacker-influenced
string is not used to build the path in the first place. The original
filename is kept only as a label for the artifact.

The directory is removed on exit. Report output can contain financial
detail, so retention is opt-in (`keep_workspace_on_failure`) and applies
only to failures, where a human is going to look.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.logging import get_logger

logger = get_logger("workspace")

# Extensions the worker will write and hand to Excel. Enforced here as
# well as server-side: the worker must not depend on the control plane
# having validated anything.
_ALLOWED_WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xlsb"})

_ZIP_MAGIC = b"PK\x03\x04"


class Workspace:
    """Use as a context manager; the directory dies with the block."""

    def __init__(
        self,
        execution_id: str,
        *,
        keep_on_failure: bool = False,
        root: Path | None = None,
    ):
        self.execution_id = execution_id
        self.keep_on_failure = keep_on_failure
        self._root = root
        self.path: Path | None = None
        self._failed = False

    def __enter__(self) -> "Workspace":
        base = self._root or Path(tempfile.gettempdir())

        # mkdtemp, not a predictable name: a predictable path in a shared
        # temp directory is a symlink/pre-creation target.
        self.path = Path(
            tempfile.mkdtemp(prefix=f"pa-copilot-{self.execution_id[:8]}-", dir=base)
        )

        logger.debug(f"Workspace created: {self.path.name}")

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._failed = exc_type is not None

        self.cleanup()

    def mark_failed(self) -> None:
        self._failed = True

    def cleanup(self) -> None:
        if self.path is None or not self.path.exists():
            return

        if self._failed and self.keep_on_failure:
            logger.warning(
                f"Workspace retained for diagnosis: {self.path}. It contains "
                "report data — delete it once the failure is understood."
            )

            return

        try:
            shutil.rmtree(self.path, ignore_errors=False)
            logger.debug("Workspace removed")
        except OSError as exc:
            # Usually Excel still holding a handle. Not fatal to the
            # execution's result, but worth surfacing: repeated leaks
            # fill the disk.
            logger.warning(
                f"Could not fully remove the workspace ({type(exc).__name__}). "
                f"Left at: {self.path}"
            )
        finally:
            self.path = None

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def write_workbook(self, content: bytes, original_filename: str) -> Path:
        """Write the workbook under a name we generate, not one we're given.

        `original_filename` is consulted only for its extension, and even
        that is validated against an allowlist. If it is missing or not
        permitted, `.xlsx` is used — a server-supplied string can change
        the suffix among three safe values and nothing else.
        """

        if self.path is None:
            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "The workspace is not open.",
            )

        if not content:
            raise WorkerError(
                WorkerErrorCode.WORKBOOK_MISSING,
                "The downloaded workbook was empty.",
            )

        if not content.startswith(_ZIP_MAGIC):
            # Independent of the server's own validation. The worker is
            # about to hand this to Excel; it verifies for itself.
            raise WorkerError(
                WorkerErrorCode.WORKBOOK_INVALID,
                "The downloaded file is not a valid Excel workbook.",
            )

        suffix = Path(original_filename or "").suffix.lower()

        if suffix not in _ALLOWED_WORKBOOK_SUFFIXES:
            suffix = ".xlsx"

        # UUID-derived name: nothing from the server reaches the path.
        target = self.path / f"workbook-{uuid.uuid4().hex}{suffix}"

        target.write_bytes(content)

        self._assert_contained(target)

        return target

    def artifact_path(self, output_format: str) -> Path:
        """A path for generated output, also under a name we generate."""

        if self.path is None:
            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "The workspace is not open.",
            )

        # Constrained to the formats this worker produces, so the format
        # string cannot introduce a suffix of its own.
        suffix = {
            "xlsx": ".xlsx",
            "pdf": ".pdf",
            "csv": ".csv",
        }.get(output_format)

        if suffix is None:
            raise WorkerError(
                WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED,
                f"This worker cannot produce '{output_format}' output.",
            )

        target = self.path / f"output-{uuid.uuid4().hex}{suffix}"

        self._assert_contained(target)

        return target

    def _assert_contained(self, target: Path) -> None:
        """Belt-and-braces containment check.

        Given that names are UUID-generated this should be unreachable.
        It exists so that a future change which does start interpolating
        a supplied name fails a test instead of shipping a traversal.
        """

        assert self.path is not None

        resolved_root = self.path.resolve()
        resolved_target = target.resolve()

        if not str(resolved_target).startswith(str(resolved_root)):
            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "Refusing to use a path outside the execution workspace.",
            )
