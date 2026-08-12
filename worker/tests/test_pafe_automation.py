"""PAfE wrapper tests against a fake that only answers documented APIs.

`FakeReporting` raises AttributeError for anything outside IBM's
documented surface, so a call to an invented method fails these tests
rather than shipping.
"""

import pytest

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.pafe.automation import PAfEAutomation
from tests.conftest import FakeReporting


def _automation(reporting) -> PAfEAutomation:
    automation = PAfEAutomation(excel_application=object())
    automation.reporting = reporting

    return automation


class TestDocumentedApiOnly:

    def test_refresh_uses_refresh_all_data_then_wait(self, fake_reporting):
        automation = _automation(fake_reporting)

        automation.refresh_all_data()
        automation.wait()

        # The documented completion mechanism, in the documented order.
        assert fake_reporting.calls == ["RefreshAllData", "Wait"]

    def test_no_sleep_is_used_for_refresh_completion(self):
        # The spec's hard requirement: Wait(), never sleep(5000).
        import inspect

        from pa_worker.execution import runner
        from pa_worker.pafe import automation

        for module in (automation, runner):
            source = inspect.getsource(module)

            assert "time.sleep" not in source, module.__name__

    def test_version_comes_from_the_documented_user_agent(self, fake_reporting):
        assert _automation(fake_reporting).version() == "2.0.99.1"

    def test_suppress_messages_is_called(self, fake_reporting):
        _automation(fake_reporting).suppress_messages(True)

        assert "SuppressMessages" in fake_reporting.calls

    def test_trace_log_is_read(self):
        reporting = FakeReporting(trace_log="automation activity")

        assert _automation(reporting).trace_log() == "automation activity"

    def test_an_undocumented_api_would_fail_loudly(self, fake_reporting):
        # Proves the fake actually constrains the surface.
        with pytest.raises(AttributeError):
            fake_reporting.RefreshEverythingPlease()


class TestLogon:

    def test_successful_logon(self):
        reporting = FakeReporting(logon_result=True)
        automation = _automation(reporting)

        automation.logon(
            url="https://tm1.example.com",
            username="svc_reports",
            password="secret",
            namespace="Planning Sample",
        )

        assert "Logon" in reporting.calls

    def test_a_false_return_is_an_auth_failure(self):
        # IBM returns False for a rejected sign-in rather than raising.
        reporting = FakeReporting(logon_result=False)

        with pytest.raises(WorkerError) as exc_info:
            _automation(reporting).logon(
                url="https://tm1.example.com",
                username="svc_reports",
                password="wrong",
                namespace="Planning Sample",
            )

        assert exc_info.value.code == WorkerErrorCode.TM1_AUTH_FAILED

    def test_credentials_never_appear_in_the_error_detail(self):
        reporting = FakeReporting(logon_result=False)

        with pytest.raises(WorkerError) as exc_info:
            _automation(reporting).logon(
                url="https://tm1.example.com",
                username="svc_reports",
                password="hunter2",
                namespace="Planning Sample",
            )

        detail = str(exc_info.value.detail)

        assert "hunter2" not in detail
        assert "svc_reports" not in detail
        assert "tm1.example.com" not in detail

    def test_logoff_is_a_noop_when_never_logged_on(self, fake_reporting):
        _automation(fake_reporting).logoff()

        assert "Logoff" not in fake_reporting.calls


class TestFailureClassification:

    def test_a_com_failure_during_refresh_is_classified(self):
        reporting = FakeReporting(fail_on={"RefreshAllData"})

        with pytest.raises(WorkerError) as exc_info:
            _automation(reporting).refresh_all_data()

        assert exc_info.value.code == WorkerErrorCode.REFRESH_FAILED

    def test_a_com_failure_during_wait_is_classified(self):
        reporting = FakeReporting(fail_on={"Wait"})

        with pytest.raises(WorkerError) as exc_info:
            _automation(reporting).wait()

        assert exc_info.value.code == WorkerErrorCode.REFRESH_FAILED

    def test_trace_log_failure_is_never_fatal(self):
        # Losing the diagnostic log must not turn a good refresh into a
        # failed report.
        class ExplodingTraceLog:
            """Only TraceLog is needed; reading it raises, as a dead COM
            object would."""

            @property
            def TraceLog(self):  # noqa: N802 - mirrors the COM name
                raise RuntimeError("COM failure reading TraceLog")

        assert _automation(ExplodingTraceLog()).trace_log() is None


class TestTraceLogClassification:
    """A clean RefreshAllData() does not prove data arrived."""

    @pytest.mark.parametrize(
        "trace,expected",
        [
            (
                "Error: could not log on to server",
                WorkerErrorCode.TM1_AUTH_FAILED,
            ),
            ("Authentication failed for user", WorkerErrorCode.TM1_AUTH_FAILED),
            ("Unauthorized", WorkerErrorCode.TM1_AUTH_FAILED),
            (
                "Unable to connect to the TM1 server",
                WorkerErrorCode.TM1_CONNECTION_FAILED,
            ),
            ("Connection refused", WorkerErrorCode.TM1_CONNECTION_FAILED),
            ("The operation timed out", WorkerErrorCode.TM1_CONNECTION_FAILED),
        ],
    )
    def test_failure_signals_are_detected(self, trace, expected):
        error = PAfEAutomation.classify_trace_log(trace)

        assert error is not None
        assert error.code == expected

    @pytest.mark.parametrize(
        "trace",
        [
            None,
            "",
            "Refresh completed successfully",
            "Retrieved 1,234 cells from Planning Sample",
        ],
    )
    def test_clean_logs_produce_no_error(self, trace):
        assert PAfEAutomation.classify_trace_log(trace) is None

    def test_detection_is_case_insensitive(self):
        assert (
            PAfEAutomation.classify_trace_log("COULD NOT LOG ON") is not None
        )
