"""The execution lifecycle, as data rather than as scattered ifs.

Nothing in this domain writes `execution.status = ...` directly. Every
write goes through `assert_transition()`, which is what makes claims like
"a succeeded execution can never go back to running" true by construction
instead of true by inspection.

Retries deliberately do NOT reopen a terminal execution. A retry is a new
row with `parent_execution_id` pointing at the failure, so the history of
what actually happened stays immutable and a delivery that already
happened cannot happen twice under the same execution id.
"""

from src.core.exceptions import ConflictException
from src.reports.enums import ExecutionStatus

_ALLOWED: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.QUEUED: frozenset(
        {
            ExecutionStatus.ASSIGNED,
            ExecutionStatus.CANCELLED,
            # Nothing ever claimed it and the queue window passed.
            ExecutionStatus.TIMED_OUT,
        }
    ),
    ExecutionStatus.ASSIGNED: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.CANCELLED,
            # The worker claimed it and died before starting; the reaper
            # puts it back rather than burning the occurrence.
            ExecutionStatus.QUEUED,
        }
    ),
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.CANCELLED,
        }
    ),
    # RETRYING is the marker on the *old* row saying "a replacement exists".
    # It is terminal for that row.
    ExecutionStatus.FAILED: frozenset({ExecutionStatus.RETRYING}),
    ExecutionStatus.TIMED_OUT: frozenset({ExecutionStatus.RETRYING}),
    ExecutionStatus.SUCCEEDED: frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
    ExecutionStatus.RETRYING: frozenset(),
}


def can_transition(
    current: ExecutionStatus,
    target: ExecutionStatus,
) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def assert_transition(
    current: ExecutionStatus,
    target: ExecutionStatus,
) -> None:
    """Raise unless `current -> target` is a legal move.

    ConflictException (409) rather than a validation error: the caller's
    request was well-formed, it just arrived after the world moved on —
    a worker reporting success for a job the reaper already timed out,
    two workers racing the same claim, a double-clicked cancel.
    """

    if not can_transition(current, target):
        raise ConflictException(
            f"Cannot move execution from {current.value} to {target.value}.",
            code="INVALID_EXECUTION_TRANSITION",
        )
