"""End-to-end worker job execution, with the Excel child faked."""

import hashlib

import pytest

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.jobs.poller import execute_job
from tests.conftest import FakeSupervisor


class TestHappyPath:

    def test_successful_job_reports_in_the_right_order(
        self, fake_client, fake_supervisor, job, config, tmp_path
    ):
        ok = execute_job(
            fake_client,
            job,
            config,
            supervisor=fake_supervisor,
            workspace_root=tmp_path,
        )

        assert ok is True

        names = fake_client.call_names

        # Artifacts must be stored *before* success is declared. A
        # SUCCEEDED execution with no artifact is worse than an honest
        # failure — nobody goes looking for it.
        assert names.index("upload_artifact") < names.index("complete_job")

        assert names.index("start_job") < names.index("download_workbook")
        assert "report_progress" in names

    def test_trace_log_and_diagnostics_are_forwarded(
        self, fake_client, fake_supervisor, job, config, tmp_path
    ):
        execute_job(
            fake_client,
            job,
            config,
            supervisor=fake_supervisor,
            workspace_root=tmp_path,
        )

        complete = next(
            call for call in fake_client.calls if call[0] == "complete_job"
        )

        assert "refresh completed" in complete[2]["trace_log"]
        assert complete[2]["diagnostics"]["pafe_version"] == "2.0.99.1"

    def test_artifact_checksum_is_computed_and_sent(
        self, fake_client, fake_supervisor, job, config, tmp_path
    ):
        execute_job(
            fake_client,
            job,
            config,
            supervisor=fake_supervisor,
            workspace_root=tmp_path,
        )

        upload = next(
            call for call in fake_client.calls if call[0] == "upload_artifact"
        )

        assert upload[2]["checksum"] == hashlib.sha256(
            b"PK\x03\x04refreshed"
        ).hexdigest()

    def test_workspace_is_removed_after_success(
        self, fake_client, fake_supervisor, job, config, tmp_path
    ):
        execute_job(
            fake_client,
            job,
            config,
            supervisor=fake_supervisor,
            workspace_root=tmp_path,
        )

        # Report output can contain financial detail — nothing is left on
        # the customer's disk after a successful run.
        assert list(tmp_path.iterdir()) == []


class TestChecksumVerification:

    def test_tampered_workbook_is_refused_before_excel_starts(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        # Bytes that do not match the checksum in the job payload.
        client = FakeClient(workbook=b"PK\x03\x04tampered-content")

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        assert ok is False

        # Excel was never invoked.
        assert fake_supervisor.progress_calls == []

        failure = next(call for call in client.calls if call[0] == "fail_job")

        assert failure[2]["error_code"] == "workbook_checksum_mismatch"

    def test_header_checksum_disagreeing_with_the_job_is_refused(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient, WORKBOOK_BYTES

        # Content matches the job, but the served header claims otherwise
        # — the two sources of truth disagree, so nothing is opened.
        client = FakeClient(workbook=WORKBOOK_BYTES, checksum="0" * 64)

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        assert ok is False
        assert fake_supervisor.progress_calls == []

    def test_non_workbook_content_is_refused(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        payload = b"MZ\x90\x00executable"

        client = FakeClient(workbook=payload)
        job["workbook"]["checksum"] = hashlib.sha256(payload).hexdigest()

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        # Checksum matches, but the worker independently verifies the
        # container before handing anything to Excel.
        assert ok is False

        failure = next(call for call in client.calls if call[0] == "fail_job")

        assert failure[2]["error_code"] == "workbook_invalid"


class TestFailureReporting:

    @pytest.mark.parametrize(
        "code",
        [
            WorkerErrorCode.EXCEL_LAUNCH_FAILED,
            WorkerErrorCode.PAFE_NOT_INSTALLED,
            WorkerErrorCode.REFRESH_FAILED,
            WorkerErrorCode.EXECUTION_TIMEOUT,
            WorkerErrorCode.EXCEL_CRASHED,
            WorkerErrorCode.TM1_CONNECTION_FAILED,
        ],
    )
    def test_every_failure_is_reported_with_its_code(
        self, fake_client, job, config, tmp_path, code
    ):
        supervisor = FakeSupervisor(
            error=WorkerError(code, "something went wrong")
        )

        ok = execute_job(
            fake_client,
            job,
            config,
            supervisor=supervisor,
            workspace_root=tmp_path,
        )

        assert ok is False

        failure = next(
            call for call in fake_client.calls if call[0] == "fail_job"
        )

        assert failure[2]["error_code"] == code.value
        # Success must never be reported for a failed run.
        assert "complete_job" not in fake_client.call_names

    def test_a_failed_upload_fails_the_execution(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        client = FakeClient()
        client.fail_uploads = True

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        assert ok is False
        # Crucially, not reported as a success with no artifact.
        assert "complete_job" not in client.call_names

        failure = next(call for call in client.calls if call[0] == "fail_job")

        assert failure[2]["error_code"] == "artifact_upload_failed"

    def test_producing_no_artifacts_is_a_failure(
        self, fake_client, job, config, tmp_path
    ):
        supervisor = FakeSupervisor(artifacts=[])

        ok = execute_job(
            fake_client,
            job,
            config,
            supervisor=supervisor,
            workspace_root=tmp_path,
        )

        assert ok is False
        assert "complete_job" not in fake_client.call_names

    def test_an_unexpected_exception_still_reports_a_failure(
        self, fake_client, job, config, tmp_path
    ):
        supervisor = FakeSupervisor(error=RuntimeError("something unforeseen"))

        ok = execute_job(
            fake_client,
            job,
            config,
            supervisor=supervisor,
            workspace_root=tmp_path,
        )

        assert ok is False

        failure = next(
            call for call in fake_client.calls if call[0] == "fail_job"
        )

        assert failure[2]["error_code"] == "internal_error"


class TestCancellation:

    def test_a_rejected_progress_call_stops_the_run(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        client = FakeClient()
        client.progress_ok = False  # server answers 409

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        assert ok is False
        assert "complete_job" not in client.call_names


class TestCompletionResilience:
    """Excel succeeded — losing the ACK must not waste that."""

    def test_completion_is_retried(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        client = FakeClient()
        client.fail_complete_times = 2

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        assert ok is True
        assert client.call_names.count("complete_job") == 3

    def test_giving_up_on_completion_is_reported_as_a_failure(
        self, fake_supervisor, job, config, tmp_path
    ):
        from tests.conftest import FakeClient

        client = FakeClient()
        client.fail_complete_times = 99

        ok = execute_job(
            client, job, config, supervisor=fake_supervisor, workspace_root=tmp_path
        )

        # Honest: the artifacts exist but the run could not be recorded,
        # so the server's reaper will time it out and retry.
        assert ok is False


class TestWorkspaceRetention:

    def test_failed_workspace_is_kept_when_configured(
        self, fake_client, job, config, tmp_path
    ):
        config.keep_workspace_on_failure = True

        supervisor = FakeSupervisor(
            error=WorkerError(WorkerErrorCode.REFRESH_FAILED, "refresh failed")
        )

        execute_job(
            fake_client,
            job,
            config,
            supervisor=supervisor,
            workspace_root=tmp_path,
        )

        assert list(tmp_path.iterdir()), "workspace should be retained"

    def test_failed_workspace_is_removed_by_default(
        self, fake_client, job, config, tmp_path
    ):
        supervisor = FakeSupervisor(
            error=WorkerError(WorkerErrorCode.REFRESH_FAILED, "refresh failed")
        )

        execute_job(
            fake_client,
            job,
            config,
            supervisor=supervisor,
            workspace_root=tmp_path,
        )

        assert list(tmp_path.iterdir()) == []
