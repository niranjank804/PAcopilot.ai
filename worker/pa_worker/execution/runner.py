"""ReportRunner — the abstraction a future native TM1 engine plugs into.

`PAfEWorkbookRunner` is the only implementation today. It runs *inside
the child process* (see supervisor.py), so it may block for as long as
Excel needs; the parent owns the clock.

The interface is deliberately narrow. A runner is given a validated job
and a workspace, and returns produced files. It does not talk to the
control plane, does not decide about retries, and does not know its own
timeout — those belong to layers that can be tested without Excel.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.excel.session import ExcelSession
from pa_worker.execution.operations import WorkerOperation
from pa_worker.execution.workspace import Workspace
from pa_worker.logging import get_logger
from pa_worker.pafe.automation import PAfEAutomation

logger = get_logger("runner")

# xlOpenXMLWorkbook — .xlsx without macros. Saving a refreshed .xlsm as
# .xlsx deliberately drops the macro project: the artifact is a report to
# be read, not a program to be run, and stripping the VBA means a
# delivered file cannot execute anything on the recipient's machine.
XL_OPEN_XML_WORKBOOK = 51


@dataclass
class ProducedArtifact:
    path: Path
    output_format: str
    checksum: str
    size_bytes: int
    mime_type: str


@dataclass
class RunResult:
    artifacts: list[ProducedArtifact] = field(default_factory=list)
    trace_log: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


MIME_TYPES = {
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "pdf": "application/pdf",
    "csv": "text/csv",
}


class ReportRunner(ABC):
    """Contract for anything that turns a job into artifacts."""

    operation: WorkerOperation

    @abstractmethod
    def validate(self, job: dict) -> None:
        """Reject a job this runner cannot execute, before starting Excel."""

    @abstractmethod
    def run(
        self,
        job: dict,
        workspace: Workspace,
        workbook_path: Path,
        *,
        progress: Callable[[str], None],
    ) -> RunResult:
        """Execute. May block; the parent process enforces the timeout."""

    def health(self) -> dict:
        """Host facts this runner needs. Overridden where meaningful."""

        return {}


class PAfEWorkbookRunner(ReportRunner):
    """REFRESH_WORKBOOK: open, RefreshAllData(), Wait(), export.

    The step sequence is fixed in code. Nothing in the job payload can
    add a step, reorder them, or introduce a call — the payload only
    supplies a workbook, a set of output formats, and optional connection
    coordinates.
    """

    operation = WorkerOperation.REFRESH_WORKBOOK

    SUPPORTED_FORMATS = frozenset({"xlsx", "pdf"})

    def __init__(
        self,
        *,
        excel_startup_timeout_seconds: int = 120,
        logon_provider: Callable[[dict], dict | None] | None = None,
    ):
        self.excel_startup_timeout_seconds = excel_startup_timeout_seconds
        # Supplies TM1 credentials from the worker's *local* store when
        # the operator has configured PAfE Logon. Returns None when the
        # workbook should refresh against the machine's existing PAfE
        # session, which is the default and the only cloud-compatible
        # path (IBM documents Logon as unable to sign in to cloud
        # systems).
        self.logon_provider = logon_provider

    def validate(self, job: dict) -> None:
        formats = [str(item) for item in job.get("output_formats") or []]

        if not formats:
            raise WorkerError(
                WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED,
                "The job requested no output formats.",
            )

        unsupported = sorted(set(formats) - self.SUPPORTED_FORMATS)

        if unsupported:
            raise WorkerError(
                WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED,
                "This worker cannot produce every requested output format.",
                detail={"unsupported": unsupported},
            )

    def run(
        self,
        job: dict,
        workspace: Workspace,
        workbook_path: Path,
        *,
        progress: Callable[[str], None],
    ) -> RunResult:
        self.validate(job)

        diagnostics: dict[str, Any] = {}
        trace_log: str | None = None
        artifacts: list[ProducedArtifact] = []

        progress("excel_starting")

        with ExcelSession(
            startup_timeout_seconds=self.excel_startup_timeout_seconds
        ) as excel:
            diagnostics["excel_version"] = excel.version
            diagnostics["excel_pid"] = excel.pid

            progress("pafe_detecting")

            pafe = PAfEAutomation(excel.application)
            pafe.connect()

            diagnostics["pafe_version"] = pafe.version()

            logger.info(f"PAfE detected (version={diagnostics['pafe_version']})")

            pafe.suppress_messages(True)

            try:
                self._maybe_logon(job, pafe, diagnostics)

                progress("workbook_opening")

                excel.open_workbook(str(workbook_path))

                progress("refresh_started")

                logger.info("Calling PAfE RefreshAllData()")
                pafe.refresh_all_data()

                # IBM's documented completion mechanism. Blocks until the
                # background refresh finishes; there is no sleep here.
                logger.info("Calling PAfE Wait() for refresh completion")
                pafe.wait()

                progress("refresh_completed")

                trace_log = pafe.trace_log()

                # RefreshAllData() returning cleanly does not prove data
                # arrived — PAfE reports connection and auth problems
                # into the trace log. Without this a silently-failed
                # refresh would be published as a current report.
                failure = PAfEAutomation.classify_trace_log(trace_log)

                if failure is not None:
                    failure.detail.update(diagnostics)

                    raise failure

                progress("exporting")

                artifacts = self._export(job, excel, workspace)

                diagnostics["artifact_count"] = len(artifacts)
            finally:
                # Before Excel closes, so the session is still live.
                pafe.logoff()

                if trace_log is None:
                    trace_log = pafe.trace_log()

        progress("excel_closed")

        return RunResult(
            artifacts=artifacts,
            trace_log=trace_log,
            diagnostics=diagnostics,
        )

    def _maybe_logon(
        self,
        job: dict,
        pafe: PAfEAutomation,
        diagnostics: dict,
    ) -> None:
        """Sign in only when the operator has configured local credentials.

        The control plane never sends credentials, so there is nothing to
        fall back on: absent local configuration the workbook refreshes
        using the PAfE session already established on the machine.
        """

        connection = job.get("connection")

        if not connection or self.logon_provider is None:
            diagnostics["auth_mode"] = "existing_pafe_session"

            return

        credentials = self.logon_provider(connection)

        if not credentials:
            diagnostics["auth_mode"] = "existing_pafe_session"

            return

        diagnostics["auth_mode"] = "pafe_logon"

        pafe.logon(
            url=credentials["url"],
            username=credentials["username"],
            password=credentials["password"],
            namespace=credentials.get("namespace", ""),
        )

    def _export(
        self,
        job: dict,
        excel: ExcelSession,
        workspace: Workspace,
    ) -> list[ProducedArtifact]:
        produced: list[ProducedArtifact] = []

        for output_format in job.get("output_formats") or []:
            target = workspace.artifact_path(output_format)

            if output_format == "xlsx":
                excel.save_workbook_as(str(target), XL_OPEN_XML_WORKBOOK)
            elif output_format == "pdf":
                excel.export_pdf(str(target))
            else:
                raise WorkerError(
                    WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED,
                    f"This worker cannot produce '{output_format}' output.",
                )

            # Excel's export calls are asynchronous enough that a missing
            # or empty file is a real outcome, not a theoretical one.
            # Verifying is what stops a zero-byte artifact being uploaded
            # as a successful report.
            if not target.exists() or target.stat().st_size == 0:
                raise WorkerError(
                    WorkerErrorCode.EXPORT_FAILED,
                    f"Excel did not produce a {output_format} file.",
                )

            content = target.read_bytes()

            produced.append(
                ProducedArtifact(
                    path=target,
                    output_format=output_format,
                    checksum=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    mime_type=MIME_TYPES.get(
                        output_format, "application/octet-stream"
                    ),
                )
            )

            logger.info(
                f"Produced {output_format} artifact ({len(content)} bytes)"
            )

        return produced


RUNNERS: dict[WorkerOperation, type[ReportRunner]] = {
    WorkerOperation.REFRESH_WORKBOOK: PAfEWorkbookRunner,
}
