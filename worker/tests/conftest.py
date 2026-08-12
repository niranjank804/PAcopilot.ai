"""Fakes for the parts of the worker that need Windows and Excel.

The COM boundary is narrow on purpose — `ExcelSession` and
`PAfEAutomation` — so everything above it (checksum verification,
workspace isolation, the allowlist, artifact upload, failure reporting,
the poll loop) can be tested on any platform. What cannot be tested
without a real PAfE install is explicitly marked NOT VERIFIED in the POC
report rather than faked and claimed.
"""

import hashlib
import json

import pytest

from pa_worker.config import WorkerConfig, WorkerCredentials

WORKBOOK_BYTES = b"PK\x03\x04" + b"\x00" * 256
WORKBOOK_CHECKSUM = hashlib.sha256(WORKBOOK_BYTES).hexdigest()


@pytest.fixture
def config(tmp_path):
    return WorkerConfig(
        server_url="https://pa-copilot.test",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0.01,
        max_execution_seconds=60,
    )


@pytest.fixture
def credentials():
    return WorkerCredentials(
        worker_id="11111111-1111-1111-1111-111111111111",
        worker_secret="pacw-secret-testtesttesttesttesttest",
        organization_id="22222222-2222-2222-2222-222222222222",
        secret_version=1,
    )


@pytest.fixture
def job():
    return {
        "execution_id": "33333333-3333-3333-3333-333333333333",
        "report_id": "44444444-4444-4444-4444-444444444444",
        "correlation_id": "55555555-5555-5555-5555-555555555555",
        "operation": "REFRESH_WORKBOOK",
        "output_formats": ["xlsx"],
        "workbook": {
            "id": "66666666-6666-6666-6666-666666666666",
            "filename": "Monthly P&L.xlsx",
            "checksum": WORKBOOK_CHECKSUM,
            "size_bytes": len(WORKBOOK_BYTES),
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        "connection": None,
        "timeout_seconds": 60,
        "lease_seconds": 120,
        "attempt": 1,
    }


class FakeClient:
    """Records every call, so tests can assert ordering and idempotency."""

    def __init__(self, *, workbook: bytes = WORKBOOK_BYTES, checksum=None):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.workbook = workbook
        self.checksum = (
            checksum if checksum is not None else hashlib.sha256(workbook).hexdigest()
        )
        self.progress_ok = True
        self.fail_uploads = False
        self.fail_complete_times = 0
        self._complete_attempts = 0

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    @property
    def call_names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def start_job(self, execution_id):
        self._record("start_job", execution_id)

        return {"status": "running"}

    def download_workbook(self, execution_id):
        self._record("download_workbook", execution_id)

        return self.workbook, self.checksum

    def report_progress(self, execution_id, step):
        self._record("report_progress", execution_id, step)

        if not self.progress_ok:
            from pa_worker.errors import ControlPlaneError

            raise ControlPlaneError("cancelled", status_code=409)

        return {"status": "running"}

    def upload_artifact(self, execution_id, **kwargs):
        self._record("upload_artifact", execution_id, **kwargs)

        if self.fail_uploads:
            from pa_worker.errors import ControlPlaneError

            raise ControlPlaneError("upload failed", status_code=500)

        return {"created": True, "artifact_id": "artifact-1"}

    def complete_job(self, execution_id, **kwargs):
        self._record("complete_job", execution_id, **kwargs)

        self._complete_attempts += 1

        if self._complete_attempts <= self.fail_complete_times:
            from pa_worker.errors import ControlPlaneError

            raise ControlPlaneError("temporarily unavailable", status_code=503)

        return {"status": "succeeded"}

    def fail_job(self, execution_id, **kwargs):
        self._record("fail_job", execution_id, **kwargs)

        return {"status": "failed"}

    def heartbeat(self, **kwargs):
        self._record("heartbeat", **kwargs)

        return {
            "status": "online",
            "heartbeat_interval_seconds": 30,
            "active_execution_ids": [],
        }

    def claim_job(self):
        self._record("claim_job")

        return None


@pytest.fixture
def fake_client():
    return FakeClient()


class FakeSupervisor:
    """Stands in for the Excel child process."""

    def __init__(self, *, artifacts=None, error=None, trace_log=None):
        self.artifacts = artifacts or []
        self.error = error
        self.trace_log = trace_log
        self.progress_calls: list[str] = []

    def run(self, job, *, workspace_path, workbook_path, on_progress):
        from pa_worker.execution.supervisor import ChildResult

        # Exercise the lease-renewal path the real supervisor drives.
        for step in ("excel_starting", "refresh_started", "refresh_completed"):
            self.progress_calls.append(step)

            if not on_progress(step):
                from pa_worker.errors import WorkerError, WorkerErrorCode

                raise WorkerError(
                    WorkerErrorCode.CANCELLED,
                    "The execution was cancelled.",
                )

        if self.error is not None:
            raise self.error

        produced = []

        for artifact in self.artifacts:
            path = workspace_path / artifact["name"]
            path.write_bytes(artifact["content"])

            produced.append(
                {
                    "path": str(path),
                    "output_format": artifact["output_format"],
                    "checksum": hashlib.sha256(artifact["content"]).hexdigest(),
                    "size_bytes": len(artifact["content"]),
                    "mime_type": "application/octet-stream",
                }
            )

        return ChildResult(
            ok=True,
            artifacts=produced,
            trace_log=self.trace_log,
            diagnostics={"excel_version": "16.0", "pafe_version": "2.0.99.1"},
        )


@pytest.fixture
def fake_supervisor():
    return FakeSupervisor(
        artifacts=[
            {
                "name": "out.xlsx",
                "content": b"PK\x03\x04refreshed",
                "output_format": "xlsx",
            }
        ],
        trace_log="PAfE automation log: refresh completed",
    )


class FakeReporting:
    """A stand-in for the IBM automation COM object.

    Mirrors the documented surface only: the methods this fake responds
    to are exactly the ones verified against IBM's PAx API source. If the
    production code ever calls something IBM does not document, this fake
    raises AttributeError and the test fails — which is the point.
    """

    _DOCUMENTED = {
        "Logon",
        "LogonSSO",
        "Logoff",
        "RefreshAllData",
        "RefreshAllDataAndFormat",
        "RefreshBook",
        "RefreshSheet",
        "Wait",
        "TraceLog",
        "TraceError",
        "SuppressMessages",
        "UserAgent",
        "UserAgentSCRelease",
        "UserAgentSCReleaseFull",
    }

    def __init__(self, *, trace_log="", logon_result=True, fail_on=None):
        self.calls: list[str] = []
        self.TraceLog = trace_log
        self.UserAgentSCReleaseFull = "2.0.99.1"
        self.UserAgent = "PAfE/2.0.99.1 (test); Excel/16.0"
        self._logon_result = logon_result
        self._fail_on = fail_on or set()

    def __getattr__(self, name):
        if name not in self._DOCUMENTED:
            raise AttributeError(
                f"{name} is not a documented IBM PAx automation API"
            )

        def call(*args, **kwargs):
            self.calls.append(name)

            if name in self._fail_on:
                raise RuntimeError(f"COM failure in {name}")

            if name == "Logon":
                return self._logon_result

            return None

        return call


@pytest.fixture
def fake_reporting():
    return FakeReporting()
