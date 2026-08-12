import pytest

from src.core.exceptions import ConflictException
from src.reports.enums import ExecutionStatus
from src.reports.state_machine import assert_transition, can_transition


class TestHappyPath:

    def test_poc_lifecycle_is_permitted(self):
        assert can_transition(ExecutionStatus.QUEUED, ExecutionStatus.ASSIGNED)
        assert can_transition(ExecutionStatus.ASSIGNED, ExecutionStatus.RUNNING)
        assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED)

    def test_failure_and_timeout_from_running(self):
        assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.FAILED)
        assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.TIMED_OUT)

    def test_retry_marks_the_old_row(self):
        assert can_transition(ExecutionStatus.FAILED, ExecutionStatus.RETRYING)
        assert can_transition(ExecutionStatus.TIMED_OUT, ExecutionStatus.RETRYING)

    def test_a_crashed_worker_releases_an_assigned_job_back_to_the_queue(self):
        assert can_transition(ExecutionStatus.ASSIGNED, ExecutionStatus.QUEUED)


class TestForbiddenTransitions:
    """The specific moves that would corrupt history or double-deliver."""

    def test_succeeded_can_never_run_again(self):
        # The single most important invariant: a completed execution is
        # immutable, so anything already delivered for it cannot be
        # delivered a second time under the same id.
        assert not can_transition(
            ExecutionStatus.SUCCEEDED, ExecutionStatus.RUNNING
        )

    def test_succeeded_is_fully_terminal(self):
        for target in ExecutionStatus:
            assert not can_transition(ExecutionStatus.SUCCEEDED, target)

    def test_cancelled_is_fully_terminal(self):
        for target in ExecutionStatus:
            assert not can_transition(ExecutionStatus.CANCELLED, target)

    def test_retrying_is_terminal_for_the_old_row(self):
        # The replacement is a new row; this one is history.
        for target in ExecutionStatus:
            assert not can_transition(ExecutionStatus.RETRYING, target)

    def test_a_queued_job_cannot_start_without_being_claimed(self):
        assert not can_transition(ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)

    def test_succeeded_cannot_be_reached_without_running(self):
        assert not can_transition(
            ExecutionStatus.ASSIGNED, ExecutionStatus.SUCCEEDED
        )
        assert not can_transition(
            ExecutionStatus.QUEUED, ExecutionStatus.SUCCEEDED
        )

    def test_a_failed_execution_cannot_be_declared_successful(self):
        assert not can_transition(
            ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED
        )


class TestAssertTransition:

    def test_permitted_transition_is_silent(self):
        assert_transition(ExecutionStatus.QUEUED, ExecutionStatus.ASSIGNED)

    def test_forbidden_transition_raises_conflict_not_validation(self):
        # 409, because the request was well-formed and simply arrived
        # after the world moved on — a worker reporting success for a job
        # the reaper already timed out.
        with pytest.raises(ConflictException) as exc_info:
            assert_transition(
                ExecutionStatus.SUCCEEDED, ExecutionStatus.RUNNING
            )

        assert exc_info.value.code == "INVALID_EXECUTION_TRANSITION"
        assert exc_info.value.status_code == 409

    def test_error_message_names_both_states(self):
        with pytest.raises(ConflictException) as exc_info:
            assert_transition(ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED)

        assert "succeeded" in exc_info.value.message
        assert "failed" in exc_info.value.message


class TestCoverage:

    def test_every_status_has_an_entry(self):
        # A status with no entry silently becomes terminal, which is a
        # quiet way to lose a job. Force the table to stay complete.
        for status in ExecutionStatus:
            can_transition(status, ExecutionStatus.FAILED)
