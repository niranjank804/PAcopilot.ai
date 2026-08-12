"""Child process entry point: the only place Excel is touched.

Runs as `python -m pa_worker.execution.child`. It reads a job
specification as JSON on stdin, executes it, and writes a single JSON
result to stdout. It has no network access to the control plane and no
credentials for it — the parent does all the reporting.

Why a separate process at all: IBM's `Wait()` blocks the calling thread
until the PAfE refresh completes and offers no cancellation. A thread
cannot be killed in Python, and a blocking COM call cannot be
interrupted, so a TM1 server that never answers would hang the worker
forever. Putting the Excel session in a child means the parent can
enforce the timeout the only way that actually works: by terminating the
process and everything it owns.

stdout carries exactly one JSON document. Anything the runner logs goes
to stderr, so a stray print cannot corrupt the result channel.
"""

import json
import sys
from pathlib import Path
from typing import Any

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.execution.operations import resolve_operation
from pa_worker.execution.runner import RUNNERS
from pa_worker.execution.workspace import Workspace
from pa_worker.logging import configure, get_logger, redact, set_context

logger = get_logger("child")


def _emit(payload: dict[str, Any]) -> None:
    """Write the one and only result document to stdout."""

    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def main() -> int:
    raw = sys.stdin.read()

    try:
        spec = json.loads(raw)
    except ValueError:
        _emit(
            {
                "ok": False,
                "error_code": WorkerErrorCode.INTERNAL_ERROR.value,
                "message": "The child process received an unreadable job.",
                "detail": {},
            }
        )

        return 2

    job = spec["job"]
    workspace_path = Path(spec["workspace_path"])
    workbook_path = Path(spec["workbook_path"])
    progress_path = Path(spec["progress_path"])

    configure(level=spec.get("log_level", "INFO"))

    set_context(
        execution_id=job.get("execution_id"),
        correlation_id=job.get("correlation_id"),
        report_id=job.get("report_id"),
    )

    def progress(step: str) -> None:
        """Publish the current step for the parent to read.

        A file rather than stdout: stdout is reserved for the single
        result document, and the parent needs to read progress *while*
        the child is still blocked inside Wait().
        """

        try:
            progress_path.write_text(step, encoding="utf-8")
        except OSError:
            pass

        logger.info(f"step={step}")

    try:
        operation = resolve_operation(job.get("operation", ""))

        runner_class = RUNNERS.get(operation)

        if runner_class is None:
            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "No runner is registered for this operation.",
                detail={"operation": operation.value},
            )

        runner = runner_class(
            excel_startup_timeout_seconds=spec.get(
                "excel_startup_timeout_seconds", 120
            )
        )

        # The workspace already exists — the parent created it and
        # downloaded the workbook into it, so a checksum failure never
        # reaches the point of starting Excel.
        workspace = Workspace(job["execution_id"])
        workspace.path = workspace_path

        result = runner.run(job, workspace, workbook_path, progress=progress)

        _emit(
            {
                "ok": True,
                "artifacts": [
                    {
                        "path": str(artifact.path),
                        "output_format": artifact.output_format,
                        "checksum": artifact.checksum,
                        "size_bytes": artifact.size_bytes,
                        "mime_type": artifact.mime_type,
                    }
                    for artifact in result.artifacts
                ],
                "trace_log": redact(result.trace_log) if result.trace_log else None,
                "diagnostics": redact(result.diagnostics),
            }
        )

        return 0

    except WorkerError as exc:
        logger.error(f"Execution failed: {exc.code.value}")

        _emit(
            {
                "ok": False,
                "error_code": exc.code.value,
                "message": redact(exc.message),
                "detail": redact(exc.detail),
            }
        )

        return 1

    except BaseException as exc:  # noqa: BLE001
        # Includes MemoryError and the COM-level failures that surface as
        # bare exceptions. The type name only — a COM error string can
        # embed a file path or a server URL.
        logger.exception("Unhandled error in the execution child process")

        _emit(
            {
                "ok": False,
                "error_code": WorkerErrorCode.INTERNAL_ERROR.value,
                "message": "The execution failed unexpectedly.",
                "detail": {"exception": type(exc).__name__},
            }
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
