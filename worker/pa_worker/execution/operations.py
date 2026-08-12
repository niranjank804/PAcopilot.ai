"""The worker's half of the operation allowlist.

The control plane sends an operation *name*. This module is the only
thing that turns a name into behaviour, and it does so by dictionary
lookup against a fixed set — never by `getattr`, never by `eval`, never
by importing a module named in the payload, and never by building a
command line.

That distinction is the whole security property. A payload can select
which of two hard-coded functions runs. It cannot describe a new one.

A name with no entry here raises. An operation the control plane
considers valid but this worker has not implemented therefore fails
loudly and is classified as REQUIRES_HUMAN rather than being ignored or
guessed at.
"""

from enum import Enum

from pa_worker.errors import WorkerError, WorkerErrorCode


class WorkerOperation(str, Enum):
    """Mirrors `backend/src/reports/operations.py`.

    Only REFRESH_WORKBOOK has a handler. The others are named so the two
    sides agree on vocabulary; asking for one today is an error, not a
    silent no-op.
    """

    REFRESH_WORKBOOK = "REFRESH_WORKBOOK"

    # Reserved — no handler.
    REFRESH_SHEET = "REFRESH_SHEET"
    EXPORT_XLSX = "EXPORT_XLSX"
    EXPORT_PDF = "EXPORT_PDF"


# The implemented set. Membership here is what makes an operation
# runnable — adding an enum member above is not enough on its own.
ALLOWED_OPERATIONS = frozenset({WorkerOperation.REFRESH_WORKBOOK})


def resolve_operation(name: str) -> WorkerOperation:
    """Validate an operation name from the wire.

    Both steps matter: the value must be a member of the enum (so an
    arbitrary string cannot pass), and it must be in the implemented set
    (so a reserved name cannot reach a handler that does not exist).
    """

    try:
        operation = WorkerOperation(name)
    except ValueError:
        raise WorkerError(
            WorkerErrorCode.INTERNAL_ERROR,
            "The control plane requested an operation this worker does not "
            "recognise.",
            detail={"requested_operation": str(name)[:50]},
        )

    if operation not in ALLOWED_OPERATIONS:
        raise WorkerError(
            WorkerErrorCode.INTERNAL_ERROR,
            "The control plane requested an operation this worker version "
            "does not implement.",
            detail={"requested_operation": operation.value},
        )

    return operation
