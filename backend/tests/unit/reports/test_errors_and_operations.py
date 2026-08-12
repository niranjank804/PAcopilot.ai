import pytest

from src.core.exceptions import ValidationException
from src.database.models.report_definition import ReportDefinition
from src.reports.enums import RetryClass
from src.reports.errors import (
    ReportErrorCode,
    coerce_error_code,
    message_for,
    retry_class_for,
)
from src.reports.operations import (
    IMPLEMENTED_OPERATIONS,
    WorkerOperation,
    operation_for_report,
)


class TestRetryClassification:
    """The specific classifications the spec calls out."""

    @pytest.mark.parametrize(
        "code",
        [
            ReportErrorCode.WORKER_OFFLINE,
            ReportErrorCode.TM1_CONNECTION_FAILED,
            ReportErrorCode.EXCEL_CRASHED,
            ReportErrorCode.EXCEL_LAUNCH_FAILED,
            ReportErrorCode.EXECUTION_TIMEOUT,
            ReportErrorCode.WORKER_LEASE_EXPIRED,
        ],
    )
    def test_transient_infrastructure_is_retryable(self, code):
        assert retry_class_for(code) == RetryClass.RETRYABLE

    @pytest.mark.parametrize(
        "code",
        [
            ReportErrorCode.WORKBOOK_INVALID,
            ReportErrorCode.WORKBOOK_CHECKSUM_MISMATCH,
            ReportErrorCode.WORKBOOK_MISSING,
            ReportErrorCode.CANCELLED,
        ],
    )
    def test_deterministic_failures_are_not_retryable(self, code):
        assert retry_class_for(code) == RetryClass.NON_RETRYABLE

    @pytest.mark.parametrize(
        "code",
        [
            ReportErrorCode.TM1_AUTH_FAILED,
            ReportErrorCode.INVALID_RECIPIENT,
            ReportErrorCode.PAFE_NOT_INSTALLED,
            ReportErrorCode.PAFE_API_UNAVAILABLE,
        ],
    )
    def test_failures_needing_a_person_are_flagged_as_such(self, code):
        assert retry_class_for(code) == RetryClass.REQUIRES_HUMAN

    def test_every_code_has_an_explicit_classification(self):
        # An unclassified code silently defaults to NON_RETRYABLE, which
        # is safe but wrong for anything transient. Force the decision.
        for code in ReportErrorCode:
            assert retry_class_for(code) in RetryClass

    def test_every_code_has_a_human_message(self):
        for code in ReportErrorCode:
            assert message_for(code)


class TestErrorCodeCoercion:
    """A worker is customer-operated: what it posts is input, not truth."""

    def test_known_code_passes_through(self):
        assert (
            coerce_error_code("refresh_failed") == ReportErrorCode.REFRESH_FAILED
        )

    @pytest.mark.parametrize(
        "hostile",
        [
            None,
            "",
            "definitely_not_a_code",
            "'; DROP TABLE report_executions; --",
            "../../etc/passwd",
            "a" * 500,
        ],
    )
    def test_anything_unrecognised_becomes_internal_error(self, hostile):
        # Never stored verbatim — otherwise the error column becomes an
        # unbounded attacker-controlled free-text field that the retry
        # policy then silently defaults on.
        assert coerce_error_code(hostile) == ReportErrorCode.INTERNAL_ERROR

    def test_a_coerced_code_is_still_classifiable(self):
        code = coerce_error_code("garbage")

        assert retry_class_for(code) in RetryClass


class TestOperationAllowlist:
    """The hard boundary against arbitrary code execution."""

    def test_pafe_workbook_maps_to_refresh(self):
        report = ReportDefinition(report_type="pafe_workbook")

        assert operation_for_report(report) == WorkerOperation.REFRESH_WORKBOOK

    def test_only_refresh_workbook_is_implemented(self):
        assert IMPLEMENTED_OPERATIONS == frozenset(
            {WorkerOperation.REFRESH_WORKBOOK}
        )

    def test_unimplemented_report_type_cannot_produce_an_operation(self):
        report = ReportDefinition(report_type="tm1_native")

        with pytest.raises(ValidationException):
            operation_for_report(report)

    @pytest.mark.parametrize(
        "injection",
        [
            "EXECUTE_SCRIPT",
            "Shell('cmd.exe /c whoami')",
            "REFRESH_WORKBOOK; DROP TABLE users",
            "Application.Run('EvilMacro')",
            "__import__('os').system('calc')",
        ],
    )
    def test_report_type_cannot_smuggle_an_operation(self, injection):
        # The operation is derived server-side from a validated enum
        # column. There is no path from a user-supplied string to a
        # dispatched operation.
        report = ReportDefinition(report_type=injection)

        with pytest.raises(ValidationException):
            operation_for_report(report)

    def test_parameters_are_never_consulted_for_the_operation(self):
        # Even if a report's free-form parameters name an operation, the
        # type is what decides — parameters cannot select behaviour.
        report = ReportDefinition(
            report_type="pafe_workbook",
            parameters={
                "operation": "EXECUTE_SCRIPT",
                "vba": "Shell('calc.exe')",
                "command": "rm -rf /",
            },
        )

        assert operation_for_report(report) == WorkerOperation.REFRESH_WORKBOOK
