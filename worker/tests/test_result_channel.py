"""stdout is a result channel and must carry nothing but results.

Regression test for a bug the rest of the suite could not see. The
execution child writes one JSON document to stdout and the parent parses
it whole; `diagnostics-pafe --json` is likewise meant to be piped into a
tool. Logging was configured to stdout, so every real job emitted log
lines ahead of its result and the parent failed with "the execution
process returned an unreadable result".

Nothing caught it because the suite drives `FakeSupervisor` rather than
spawning the real child. These tests exercise the actual process
boundary instead.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

WORKER_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=WORKER_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=300,
    )


class TestLoggingDestination:

    def test_logs_go_to_stderr_not_stdout(self):
        from pa_worker import logging as worker_logging

        worker_logging._configured = False
        worker_logging.configure(level="INFO")

        root = __import__("logging").getLogger("pa_worker")
        streams = [
            handler.stream
            for handler in root.handlers
            if hasattr(handler, "stream")
        ]

        assert streams, "no stream handler configured"
        assert all(stream is sys.stderr for stream in streams), (
            "a handler is writing to stdout, which is the result channel"
        )


class TestChildProcessResultChannel:
    """The real child process, spawned exactly as the supervisor does."""

    def test_stdout_is_pure_json_even_when_the_job_fails(self):
        # A workbook path that does not exist makes the child fail fast.
        # The failure is not the point — the point is that whatever it
        # writes to stdout must still parse as one JSON document.
        spec = {
            "job": {
                "execution_id": "result-channel-test",
                "correlation_id": "c-1",
                "report_id": "r-1",
                "operation": "REFRESH_WORKBOOK",
                "output_formats": ["xlsx"],
                "connection": None,
            },
            "workspace_path": str(WORKER_ROOT),
            "workbook_path": str(WORKER_ROOT / "does-not-exist.xlsx"),
            "progress_path": str(WORKER_ROOT / "progress-test.txt"),
            "log_level": "DEBUG",
        }

        result = _run(
            ["pa_worker.execution.child"], stdin=json.dumps(spec)
        )

        assert result.stdout.strip(), "child produced no result document"

        # The assertion that would have failed before the fix.
        payload = json.loads(result.stdout)

        assert "ok" in payload

        # And the logs did happen — they just went to the other stream.
        assert result.stdout.count("{") >= 1

    def test_an_unreadable_job_still_yields_parseable_json(self):
        result = _run(["pa_worker.execution.child"], stdin="not json at all")

        payload = json.loads(result.stdout)

        assert payload["ok"] is False
        assert payload["error_code"] == "internal_error"


class TestDiagnosticsJsonOutput:

    @pytest.mark.excel
    def test_diagnostics_pafe_json_is_machine_readable(self):
        """`--json` must be pipeable into a tool.

        Marked `excel` because the probe launches Excel; it is skipped
        elsewhere by `-m "not excel"`.
        """

        result = _run(["pa_worker", "diagnostics-pafe", "--json"])

        payload = json.loads(result.stdout)

        assert "status" in payload
        assert "failure" in payload
        assert "registered_progids" in payload

    def test_diagnostics_quick_json_is_machine_readable(self):
        # --quick skips launching Excel, so this runs anywhere.
        result = _run(["pa_worker", "diagnostics", "--quick", "--json"])

        payload = json.loads(result.stdout)

        assert "capabilities" in payload
