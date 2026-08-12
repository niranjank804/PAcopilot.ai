"""Runs the Excel child process under a hard timeout and a live lease.

This is where the two things that cannot be done inside the Excel
process get done:

* **Timeout.** IBM's `Wait()` blocks uninterruptibly. The only reliable
  way to bound it is from outside, by killing the process. The effective
  limit is `min(server timeout, worker max)` so neither side can be
  talked past the other's bound.

* **Lease renewal.** While the child is blocked, the parent keeps
  reporting progress to the control plane. That is what stops the
  reaper timing out a job that is legitimately taking a long time, and
  it is also how the worker learns the job was cancelled — a rejected
  progress call means the execution is no longer ours.

On timeout or cancellation the whole child *tree* is terminated, not
just the child: Excel is a grandchild (child → Excel), so killing only
the direct child would orphan the Excel process. Termination walks the
tree from the known child pid, so it still cannot touch an Excel that
this worker did not start.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.logging import get_logger

logger = get_logger("supervisor")

_PROGRESS_POLL_SECONDS = 2.0


@dataclass
class ChildResult:
    ok: bool
    artifacts: list[dict]
    trace_log: str | None
    diagnostics: dict
    error_code: str | None = None
    message: str | None = None


class ExecutionSupervisor:

    def __init__(
        self,
        *,
        max_execution_seconds: int,
        excel_startup_timeout_seconds: int = 120,
        log_level: str = "INFO",
    ):
        self.max_execution_seconds = max_execution_seconds
        self.excel_startup_timeout_seconds = excel_startup_timeout_seconds
        self.log_level = log_level

    def run(
        self,
        job: dict,
        *,
        workspace_path: Path,
        workbook_path: Path,
        on_progress: Callable[[str], bool],
    ) -> ChildResult:
        """Execute a job in a child process.

        `on_progress(step)` is called as the child advances. Returning
        False means the control plane no longer considers this execution
        ours (cancelled, reaped, or timed out server-side); the child is
        terminated immediately.
        """

        timeout = min(
            int(job.get("timeout_seconds") or self.max_execution_seconds),
            self.max_execution_seconds,
        )

        progress_path = workspace_path / "progress.txt"
        progress_path.write_text("starting", encoding="utf-8")

        spec = {
            "job": job,
            "workspace_path": str(workspace_path),
            "workbook_path": str(workbook_path),
            "progress_path": str(progress_path),
            "excel_startup_timeout_seconds": self.excel_startup_timeout_seconds,
            "log_level": self.log_level,
        }

        logger.info(
            f"Starting execution child process (timeout={timeout}s)"
        )

        process = subprocess.Popen(
            [sys.executable, "-m", "pa_worker.execution.child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Inherited, so child logs land in the worker's own log
            # instead of filling a pipe nobody drains (which would
            # deadlock a chatty child).
            stderr=None,
            text=True,
        )

        assert process.stdin is not None

        try:
            process.stdin.write(json.dumps(spec))
            process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            self._terminate_tree(process)

            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "The execution child process could not be started.",
                detail={"exception": type(exc).__name__},
            ) from exc

        deadline = time.monotonic() + timeout
        last_step: str | None = None
        cancelled = False

        while True:
            try:
                process.wait(timeout=_PROGRESS_POLL_SECONDS)

                break
            except subprocess.TimeoutExpired:
                pass

            step = self._read_progress(progress_path)

            if step and step != last_step:
                last_step = step

            # Called on every poll, not only on change: this is the lease
            # renewal, and a long refresh reports no new step for
            # minutes at a time.
            if not on_progress(last_step or "running"):
                logger.warning(
                    "The control plane no longer owns this execution; "
                    "terminating the child process."
                )
                cancelled = True

                break

            if time.monotonic() > deadline:
                logger.error(
                    f"Execution exceeded its {timeout}s limit; terminating."
                )

                self._terminate_tree(process)

                raise WorkerError(
                    WorkerErrorCode.EXECUTION_TIMEOUT,
                    "The report did not finish within the time limit.",
                    detail={
                        "timeout_seconds": timeout,
                        "last_step": last_step,
                    },
                )

        if cancelled:
            self._terminate_tree(process)

            raise WorkerError(
                WorkerErrorCode.CANCELLED,
                "The execution was cancelled or reclaimed by the server.",
                detail={"last_step": last_step},
            )

        stdout = process.stdout.read() if process.stdout else ""

        if process.returncode is None:
            self._terminate_tree(process)

        return self._parse_result(stdout, process.returncode, last_step)

    @staticmethod
    def _read_progress(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _parse_result(
        self,
        stdout: str,
        returncode: int | None,
        last_step: str | None,
    ) -> ChildResult:
        if not stdout.strip():
            # The child produced no result document. Almost always Excel
            # taking the process down with it, which is EXCEL_CRASHED
            # (retryable) rather than a generic internal error.
            raise WorkerError(
                WorkerErrorCode.EXCEL_CRASHED,
                "The execution process exited without reporting a result.",
                detail={"returncode": returncode, "last_step": last_step},
            )

        try:
            payload = json.loads(stdout)
        except ValueError:
            raise WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "The execution process returned an unreadable result.",
                detail={"returncode": returncode, "last_step": last_step},
            )

        if not payload.get("ok"):
            detail = dict(payload.get("detail") or {})
            detail["last_step"] = last_step

            raise WorkerError(
                _coerce_code(payload.get("error_code")),
                payload.get("message") or "The execution failed.",
                detail=detail,
            )

        return ChildResult(
            ok=True,
            artifacts=payload.get("artifacts") or [],
            trace_log=payload.get("trace_log"),
            diagnostics=payload.get("diagnostics") or {},
        )

    @staticmethod
    def _terminate_tree(process: subprocess.Popen) -> None:
        """Kill the child and the Excel process it started — nothing else.

        Enumerating children of a pid we started is what keeps this
        narrow. It can never reach an Excel instance belonging to an
        interactive user, because that process is not a descendant of
        this worker.
        """

        if process.poll() is not None:
            return

        try:
            import psutil

            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)

            for child in children:
                try:
                    logger.warning(
                        f"Terminating child-owned process pid={child.pid} "
                        f"name={child.name()}"
                    )
                    child.terminate()
                except psutil.Error:
                    pass

            parent.terminate()

            _, alive = psutil.wait_procs([parent, *children], timeout=15)

            for survivor in alive:
                try:
                    survivor.kill()
                except psutil.Error:
                    pass
        except ImportError:
            # Without psutil the tree cannot be walked, so only the
            # direct child is terminated. Excel may be left behind; that
            # is preferable to guessing which EXCEL.EXE to kill.
            logger.warning(
                "psutil is not installed; only the direct child process can "
                "be terminated. An Excel process may remain."
            )
            process.terminate()

            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not terminate the child tree: {type(exc).__name__}")


def _coerce_code(value: Any) -> WorkerErrorCode:
    try:
        return WorkerErrorCode(str(value))
    except ValueError:
        return WorkerErrorCode.INTERNAL_ERROR
