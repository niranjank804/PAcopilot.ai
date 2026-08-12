"""The worker's main loop, and the single-job execution it drives.

`execute_job` is written so the interesting failure paths can be tested
without Excel: the supervisor is injectable, and every step that talks to
the control plane goes through the client. The ordering of the last two
steps is the part that matters most and is easy to get wrong —

    upload artifacts  →  report success

not the reverse. If the upload fails, the execution must fail; a report
marked SUCCEEDED with no artifact is worse than an honest failure,
because nobody goes looking for it.

The complementary case — Excel succeeded, artifacts uploaded, and *then*
the network dropped before `complete` landed — is handled by the control
plane treating `complete` as idempotent. The worker retries it; an
already-SUCCEEDED execution answers success rather than a conflict.
"""

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from pa_worker.client.control_plane import ControlPlaneClient
from pa_worker.config import WorkerConfig
from pa_worker.errors import (
    AuthenticationError,
    ControlPlaneError,
    WorkerError,
    WorkerErrorCode,
)
from pa_worker.execution.supervisor import ExecutionSupervisor
from pa_worker.execution.workspace import Workspace
from pa_worker.logging import clear_context, get_logger, set_context

logger = get_logger("jobs")

# How many times to retry the final "I finished" call. The work is
# already done and the artifacts are already stored, so giving up here
# would waste a completed Excel run and produce a spurious retry.
_COMPLETE_ATTEMPTS = 5
_COMPLETE_BACKOFF_SECONDS = 3


def execute_job(
    client: ControlPlaneClient,
    job: dict,
    config: WorkerConfig,
    *,
    supervisor: ExecutionSupervisor | None = None,
    workspace_root: Path | None = None,
) -> bool:
    """Run one claimed job end to end. Returns True on success.

    Never raises for an ordinary report failure — that is reported to the
    control plane and returned as False. It only propagates errors that
    mean the worker itself is in trouble (credential rejected).
    """

    execution_id = str(job["execution_id"])

    set_context(
        execution_id=execution_id,
        correlation_id=job.get("correlation_id"),
        report_id=job.get("report_id"),
    )

    logger.info(
        f"Job claimed (operation={job.get('operation')}, "
        f"attempt={job.get('attempt')})"
    )

    supervisor = supervisor or ExecutionSupervisor(
        max_execution_seconds=config.max_execution_seconds,
        excel_startup_timeout_seconds=config.excel_startup_timeout_seconds,
        log_level=config.log_level,
    )

    def on_progress(step: str) -> bool:
        """Extend the lease; False means we no longer own this job."""

        try:
            client.report_progress(execution_id, step)

            return True
        except ControlPlaneError as exc:
            # A 409 means cancelled/reaped/timed out server-side. Any
            # other error is treated as transient: losing one progress
            # call to a blip must not abandon a running Excel session.
            if getattr(exc, "status_code", None) == 409:
                return False

            logger.warning(f"Progress call failed, continuing: {exc}")

            return True

    workspace: Workspace | None = None

    try:
        client.start_job(execution_id)

        with Workspace(
            execution_id,
            keep_on_failure=config.keep_workspace_on_failure,
            root=workspace_root,
        ) as workspace:
            workbook_path = _download_and_verify(client, job, workspace)

            result = supervisor.run(
                job,
                workspace_path=workspace.path,
                workbook_path=workbook_path,
                on_progress=on_progress,
            )

            _upload_artifacts(client, execution_id, result.artifacts)

            _complete_with_retry(
                client,
                execution_id,
                trace_log=result.trace_log,
                diagnostics=result.diagnostics,
            )

        logger.info("Job completed successfully")

        return True

    except AuthenticationError:
        # The worker's own credential is bad. Nothing to report — the
        # control plane would reject that call too.
        raise

    except WorkerError as exc:
        if workspace is not None:
            workspace.mark_failed()

        logger.error(f"Job failed: {exc.code.value} — {exc.message}")

        _report_failure(client, execution_id, exc)

        return False

    except ControlPlaneError as exc:
        # Could not reach PA-Copilot. Deliberately do not attempt to
        # report the failure over the same broken channel — the server's
        # lease reaper will time this execution out and create the retry.
        logger.error(f"Lost contact with PA-Copilot during the job: {exc}")

        return False

    except Exception as exc:  # noqa: BLE001
        if workspace is not None:
            workspace.mark_failed()

        logger.exception("Unexpected error while running the job")

        _report_failure(
            client,
            execution_id,
            WorkerError(
                WorkerErrorCode.INTERNAL_ERROR,
                "The worker failed unexpectedly.",
                detail={"exception": type(exc).__name__},
            ),
        )

        return False

    finally:
        clear_context()


def _download_and_verify(
    client: ControlPlaneClient,
    job: dict,
    workspace: Workspace,
) -> Path:
    """Fetch the workbook and prove it is the one we were promised.

    Verified against the checksum in the *job payload*, and cross-checked
    against the response header. A mismatch is fatal and non-retryable:
    the worker is about to hand this file to Excel, and opening content
    that does not match what the control plane recorded is exactly the
    thing checksums exist to prevent.
    """

    workbook = job["workbook"]
    expected = str(workbook["checksum"]).lower()

    content, header_checksum = client.download_workbook(str(job["execution_id"]))

    actual = hashlib.sha256(content).hexdigest()

    if actual != expected:
        raise WorkerError(
            WorkerErrorCode.WORKBOOK_CHECKSUM_MISMATCH,
            "The downloaded workbook did not match its recorded checksum.",
            detail={"expected_prefix": expected[:12], "actual_prefix": actual[:12]},
        )

    if header_checksum and header_checksum.lower() != expected:
        raise WorkerError(
            WorkerErrorCode.WORKBOOK_CHECKSUM_MISMATCH,
            "The workbook checksum in the job did not match the one served "
            "with the file.",
            detail={"expected_prefix": expected[:12]},
        )

    logger.info(f"Workbook verified ({len(content)} bytes, sha256 ok)")

    return workspace.write_workbook(content, str(workbook.get("filename") or ""))


def _upload_artifacts(
    client: ControlPlaneClient,
    execution_id: str,
    artifacts: list[dict],
) -> None:
    if not artifacts:
        raise WorkerError(
            WorkerErrorCode.EXPORT_FAILED,
            "The execution produced no artifacts.",
        )

    for artifact in artifacts:
        path = Path(artifact["path"])

        if not path.exists():
            raise WorkerError(
                WorkerErrorCode.EXPORT_FAILED,
                "A generated artifact was missing when uploading.",
                detail={"output_format": artifact.get("output_format")},
            )

        content = path.read_bytes()

        try:
            response = client.upload_artifact(
                execution_id,
                filename=path.name,
                output_format=artifact["output_format"],
                content=content,
                checksum=artifact["checksum"],
                mime_type=artifact["mime_type"],
            )
        except ControlPlaneError as exc:
            raise WorkerError(
                WorkerErrorCode.ARTIFACT_UPLOAD_FAILED,
                "The generated report could not be uploaded.",
                detail={
                    "output_format": artifact.get("output_format"),
                    "reason": type(exc).__name__,
                },
            ) from exc

        logger.info(
            f"Uploaded {artifact['output_format']} artifact "
            f"(created={response.get('created')})"
        )


def _complete_with_retry(
    client: ControlPlaneClient,
    execution_id: str,
    *,
    trace_log: str | None,
    diagnostics: dict,
) -> None:
    """Report success, retrying — the work is already done.

    The call is idempotent server-side, so retrying cannot double-count
    anything.
    """

    last: Exception | None = None

    for attempt in range(_COMPLETE_ATTEMPTS):
        try:
            client.complete_job(
                execution_id, trace_log=trace_log, diagnostics=diagnostics
            )

            return
        except AuthenticationError:
            raise
        except ControlPlaneError as exc:
            last = exc

            logger.warning(
                f"Could not report completion (attempt {attempt + 1}"
                f"/{_COMPLETE_ATTEMPTS}): {exc}"
            )

            time.sleep(_COMPLETE_BACKOFF_SECONDS * (attempt + 1))

    # Out of attempts. The artifacts are stored and the server's reaper
    # will time this execution out; the retry re-runs it. Wasteful, but
    # correct and visible.
    raise WorkerError(
        WorkerErrorCode.ARTIFACT_UPLOAD_FAILED,
        "The report completed but the result could not be reported to "
        "PA-Copilot.",
        detail={"reason": type(last).__name__ if last else None},
    )


def _report_failure(
    client: ControlPlaneClient,
    execution_id: str,
    error: WorkerError,
) -> None:
    """Best-effort failure reporting.

    If this cannot get through, the lease reaper handles it. Swallowing
    the secondary error is deliberate — raising here would mask the
    original failure with a networking one.
    """

    try:
        client.fail_job(
            execution_id,
            error_code=error.code.value,
            diagnostics=error.detail,
        )
    except ControlPlaneError as exc:
        logger.error(
            f"Could not report the failure to PA-Copilot: {exc}. The server "
            "will time this execution out."
        )


class JobPoller:
    """Claim → execute → repeat, with heartbeats in between."""

    def __init__(
        self,
        client: ControlPlaneClient,
        config: WorkerConfig,
        *,
        host_facts_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.client = client
        self.config = config
        self.host_facts_provider = host_facts_provider

        self._running = False
        self._last_heartbeat = 0.0
        self._heartbeat_interval = config.heartbeat_interval_seconds
        self._last_error: str | None = None

    def stop(self) -> None:
        self._running = False

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        """The main loop. `max_iterations` exists so tests can bound it."""

        self._running = True
        iterations = 0

        logger.info(
            f"Worker polling started (poll={self.config.poll_interval_seconds}s, "
            f"heartbeat={self._heartbeat_interval}s)"
        )

        while self._running:
            if max_iterations is not None and iterations >= max_iterations:
                break

            iterations += 1

            try:
                self._tick()
            except AuthenticationError as exc:
                # Disabled, revoked, or rotated. Retrying with the same
                # credential cannot help, so stop rather than hammer.
                logger.error(f"Worker authentication failed: {exc}. Stopping.")
                self._running = False

                break
            except ControlPlaneError as exc:
                # The server being down is an expected condition for a
                # long-running agent, not a reason to exit.
                self._last_error = str(exc)

                logger.warning(f"Control plane unavailable: {exc}")

                time.sleep(self.config.poll_interval_seconds)
            except Exception as exc:  # noqa: BLE001
                self._last_error = type(exc).__name__

                logger.exception("Unexpected error in the polling loop")

                time.sleep(self.config.poll_interval_seconds)

        logger.info("Worker polling stopped")

    def _tick(self) -> None:
        self._maybe_heartbeat(busy=False)

        job = self.client.claim_job()

        if job is None:
            time.sleep(self.config.poll_interval_seconds)

            return

        self._maybe_heartbeat(busy=True, force=True)

        try:
            execute_job(self.client, job, self.config)
        finally:
            # Back to idle promptly, so the console does not show BUSY
            # for a worker that has finished.
            self._maybe_heartbeat(busy=False, force=True)

    def _maybe_heartbeat(self, *, busy: bool, force: bool = False) -> None:
        now = time.monotonic()

        if not force and now - self._last_heartbeat < self._heartbeat_interval:
            return

        facts = self.host_facts_provider() if self.host_facts_provider else None

        response = self.client.heartbeat(
            busy=busy, host_facts=facts, last_error=self._last_error
        )

        self._last_heartbeat = now
        self._last_error = None

        # The server owns the cadence — adopt what it asks for rather
        # than keeping a local value that can drift from the lease.
        interval = (response or {}).get("heartbeat_interval_seconds")

        if interval:
            self._heartbeat_interval = float(interval)

        orphaned = (response or {}).get("active_execution_ids") or []

        if orphaned and not busy:
            # We hold leases on work we are not running — this worker
            # restarted mid-job. Say so; the reaper will reclaim them.
            logger.warning(
                f"The server still holds {len(orphaned)} execution(s) for "
                "this worker. They will be reclaimed when their lease "
                "expires."
            )
