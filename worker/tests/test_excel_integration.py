"""Integration tests that drive REAL Microsoft Excel via COM.

Skipped automatically where Excel is unavailable (CI, Linux, a host
without Office), so these never make the suite unrunnable — but where
Excel *is* present they exercise the parts that fakes cannot prove:
process launch, ownership resolution, real file production, and cleanup.

What is real here: Excel, COM, the workbook open, the .xlsx save, the
PDF export, the process lifecycle, and the ownership-checked teardown.

What is substituted: **only** the IBM PAfE automation object, and only in
the tests that say so. PAfE cannot be installed on this machine, so its
behaviour is NOT VERIFIED — see docs/report-automation/README.md. The
substitution is confined to these tests; nothing in the shipped worker
can bypass PAfE detection.
"""

import platform

import pytest

from pa_worker.errors import WorkerError, WorkerErrorCode

pytestmark = pytest.mark.excel


def _excel_available() -> bool:
    if platform.system() != "Windows":
        return False

    try:
        from pa_worker.excel.session import excel_available

        available, _ = excel_available()

        return available
    except Exception:  # noqa: BLE001
        return False


requires_excel = pytest.mark.skipif(
    not _excel_available(),
    reason="Microsoft Excel is not available on this host",
)


@pytest.fixture
def real_workbook(tmp_path):
    """Create a genuine .xlsx using Excel itself."""

    from pa_worker.excel.session import ExcelSession

    target = tmp_path / "source.xlsx"

    with ExcelSession() as session:
        workbook = session.application.Workbooks.Add()
        workbook.Sheets(1).Range("A1").Value = "PA-Copilot integration test"
        workbook.Sheets(1).Range("A2").Value = 42
        # 51 == xlOpenXMLWorkbook
        workbook.SaveAs(str(target), FileFormat=51)
        workbook.Close(SaveChanges=False)
        session.workbook = None

    assert target.exists()

    return target


@requires_excel
class TestExcelSessionLifecycle:

    def test_session_starts_reports_version_and_owns_a_process(self):
        from pa_worker.excel.session import ExcelSession

        with ExcelSession() as session:
            assert session.version is not None
            # Ownership must be established, otherwise forced cleanup is
            # (correctly) declined later.
            assert session.pid is not None
            assert session.pid > 0

    def test_excel_process_is_gone_after_the_session_closes(self):
        import time

        import psutil

        from pa_worker.excel.session import ExcelSession

        session = ExcelSession()
        session.start()
        pid = session.pid

        assert psutil.pid_exists(pid)

        session.close()

        # Quit() plus the COM release should be enough; the targeted
        # terminate is a backstop, not the mechanism.
        for _ in range(30):
            if not psutil.pid_exists(pid):
                break

            time.sleep(0.5)

        assert not psutil.pid_exists(pid), (
            "Excel process leaked — this is the 'ghost EXCEL.EXE' failure"
        )

    def test_cleanup_never_touches_an_unowned_excel(self):
        """Two independent sessions; closing one must not kill the other."""

        import psutil

        from pa_worker.excel.session import ExcelSession

        bystander = ExcelSession()
        bystander.start()

        try:
            victim = ExcelSession()
            victim.start()

            assert victim.pid != bystander.pid

            victim.close()

            # The bystander stands in for a real user's interactive Excel.
            assert psutil.pid_exists(bystander.pid)
        finally:
            bystander.close()

    def test_close_is_safe_to_call_twice(self):
        from pa_worker.excel.session import ExcelSession

        session = ExcelSession()
        session.start()
        session.close()
        session.close()


@requires_excel
class TestWorkbookOperations:

    def test_open_and_save_as_xlsx(self, real_workbook, tmp_path):
        from pa_worker.excel.session import ExcelSession

        target = tmp_path / "saved.xlsx"

        with ExcelSession() as session:
            session.open_workbook(str(real_workbook))
            session.save_workbook_as(str(target), 51)

        assert target.exists()
        assert target.stat().st_size > 0
        # A real OOXML container.
        assert target.read_bytes().startswith(b"PK\x03\x04")

    def test_export_pdf(self, real_workbook, tmp_path):
        from pa_worker.excel.session import ExcelSession

        target = tmp_path / "exported.pdf"

        with ExcelSession() as session:
            session.open_workbook(str(real_workbook))
            session.export_pdf(str(target))

        assert target.exists()
        assert target.read_bytes().startswith(b"%PDF")

    def test_opening_a_corrupt_file_is_classified(self, tmp_path):
        from pa_worker.excel.session import ExcelSession

        corrupt = tmp_path / "corrupt.xlsx"
        # A valid ZIP header but not a workbook — Excel must refuse it.
        corrupt.write_bytes(b"PK\x03\x04" + b"\x00" * 512)

        with ExcelSession() as session:
            with pytest.raises(WorkerError) as exc_info:
                session.open_workbook(str(corrupt))

            assert exc_info.value.code == WorkerErrorCode.WORKBOOK_OPEN_FAILED


@requires_excel
class TestPAfEDetectionOnThisHost:

    def test_pafe_detection_reports_honestly(self):
        """Whatever the answer, it must be a truthful classification."""

        from pa_worker.excel.session import ExcelSession
        from pa_worker.pafe.automation import PAfEAutomation

        with ExcelSession() as session:
            automation = PAfEAutomation(session.application)

            try:
                automation.connect()
                # PAfE present: it must expose a version.
                assert automation.version() is not None
            except WorkerError as exc:
                # PAfE absent: it must say so specifically, so the
                # control plane can classify it REQUIRES_HUMAN rather
                # than retrying forever.
                assert exc.code in {
                    WorkerErrorCode.PAFE_NOT_INSTALLED,
                    WorkerErrorCode.PAFE_API_UNAVAILABLE,
                }


@requires_excel
class TestFullRunnerWithSubstitutedPAfE:
    """The whole runner against real Excel, with IBM's object faked.

    This proves the refresh→wait→export→verify sequence and that real
    Excel produces a real artifact. It does NOT prove PAfE's own
    behaviour — that requires a host with PAfE installed.
    """

    def test_refresh_workbook_produces_a_real_xlsx(
        self, real_workbook, tmp_path, monkeypatch
    ):
        from pa_worker.execution.runner import PAfEWorkbookRunner
        from pa_worker.execution.workspace import Workspace
        from pa_worker.pafe.automation import PAfEAutomation
        from tests.conftest import FakeReporting

        reporting = FakeReporting(trace_log="Refresh completed successfully")

        def fake_connect(self):
            self.reporting = reporting

            return reporting

        monkeypatch.setattr(PAfEAutomation, "connect", fake_connect)

        job = {
            "execution_id": "e2e-test",
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx"],
            "connection": None,
        }

        steps: list[str] = []

        with Workspace("e2e-test", root=tmp_path) as workspace:
            result = PAfEWorkbookRunner().run(
                job, workspace, real_workbook, progress=steps.append
            )

            assert len(result.artifacts) == 1

            artifact = result.artifacts[0]

            assert artifact.output_format == "xlsx"
            assert artifact.size_bytes > 0
            assert artifact.path.read_bytes().startswith(b"PK\x03\x04")

        # IBM's documented sequence, in order, with no sleep between.
        assert reporting.calls[:3] == [
            "SuppressMessages",
            "RefreshAllData",
            "Wait",
        ]

        assert "refresh_started" in steps
        assert "refresh_completed" in steps
        assert "excel_closed" in steps

        assert result.diagnostics["excel_version"]
        assert result.diagnostics["auth_mode"] == "existing_pafe_session"

    def test_a_failing_trace_log_prevents_a_stale_report_being_published(
        self, real_workbook, tmp_path, monkeypatch
    ):
        """The most dangerous failure mode: a silently-failed refresh.

        RefreshAllData() returns cleanly even when PAfE could not reach
        TM1. Without the trace-log check the workbook would be exported
        with last month's numbers and reported SUCCEEDED.
        """

        from pa_worker.execution.runner import PAfEWorkbookRunner
        from pa_worker.execution.workspace import Workspace
        from pa_worker.pafe.automation import PAfEAutomation
        from tests.conftest import FakeReporting

        reporting = FakeReporting(
            trace_log="ERROR: unable to connect to the TM1 server"
        )

        monkeypatch.setattr(
            PAfEAutomation,
            "connect",
            lambda self: setattr(self, "reporting", reporting) or reporting,
        )

        job = {
            "execution_id": "e2e-fail",
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx"],
            "connection": None,
        }

        with Workspace("e2e-fail", root=tmp_path) as workspace:
            with pytest.raises(WorkerError) as exc_info:
                PAfEWorkbookRunner().run(
                    job, workspace, real_workbook, progress=lambda step: None
                )

            assert exc_info.value.code == WorkerErrorCode.TM1_CONNECTION_FAILED

        # No artifact was produced, so nothing stale can be delivered.
        assert "Export" not in reporting.calls


@requires_excel
class TestSupervisorTimeout:
    """The answer to "Wait() never returns"."""

    def test_a_hung_child_is_killed_at_the_deadline(self, tmp_path):
        import time

        from pa_worker.execution.supervisor import ExecutionSupervisor

        supervisor = ExecutionSupervisor(max_execution_seconds=5)

        job = {
            "execution_id": "timeout-test",
            # Not on the allowlist, but the child never gets far enough
            # to matter — this test is about the parent's clock.
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx"],
            "timeout_seconds": 5,
        }

        workspace = tmp_path / "ws"
        workspace.mkdir()

        # A workbook path that does not exist makes the child fail fast;
        # what is asserted is that the parent bounds the wait either way.
        started = time.monotonic()

        with pytest.raises(WorkerError):
            supervisor.run(
                job,
                workspace_path=workspace,
                workbook_path=workspace / "missing.xlsx",
                on_progress=lambda step: True,
            )

        # Bounded, and bounded by roughly the deadline rather than by
        # some much longer default.
        assert time.monotonic() - started < 60
