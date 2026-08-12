"""Excel COM lifecycle, with process ownership that makes cleanup safe.

The dangerous, common shortcut in Excel automation is to recover from a
hung session by killing every EXCEL.EXE on the machine. On a customer's
workstation or Citrix host that destroys unsaved work belonging to real
people. This module never does that.

Instead:

* `DispatchEx` starts a *dedicated* Excel instance rather than attaching
  to whatever is already running.
* Its process id is resolved from the instance's own window handle, and
  the process's creation time is recorded alongside it. The pair
  (pid, create_time) is what "our Excel" means — a pid alone is
  ambiguous after the OS recycles it.
* Forced termination only ever targets that exact pair, and only after a
  graceful `Quit()` has been tried and given time to work. If ownership
  cannot be established, the worker does not force anything; it reports
  the failure and lets an operator look.

The COM imports are deliberately lazy so this module can be imported —
and most of it unit-tested with a fake — on a machine with no Excel and
no pywin32, which is what the CI environment is.
"""

import time
from typing import Any

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.logging import get_logger

logger = get_logger("excel")

# Excel's own "another operation is in progress" rejection. Retrying
# briefly is correct — it means Excel is busy, not broken.
_RPC_RETRY_CODES = (-2147417846, -2147418111)  # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL


def _win32():
    """Import pywin32 on demand, with a clear failure if it is absent."""

    try:
        import pythoncom
        import win32api
        import win32com.client
        import win32process

        return pythoncom, win32com.client, win32process, win32api
    except ImportError as exc:
        raise WorkerError(
            WorkerErrorCode.EXCEL_LAUNCH_FAILED,
            "pywin32 is not installed. The worker must run on Windows with "
            "pywin32 available.",
        ) from exc


def excel_available() -> tuple[bool, str | None]:
    """Probe for Excel without committing to a full session.

    Used by `pa-worker diagnostics` and at enrollment, so the worker only
    ever claims the EXCEL capability on a host where this succeeded.
    """

    try:
        pythoncom, client, _, _ = _win32()
    except WorkerError:
        return False, None

    pythoncom.CoInitialize()

    excel = None

    try:
        excel = client.DispatchEx("Excel.Application")
        version = str(excel.Version)

        return True, version
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.debug(f"Excel probe failed: {type(exc).__name__}")

        return False, None
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:  # noqa: BLE001
                pass

        pythoncom.CoUninitialize()


class ExcelSession:
    """A dedicated Excel instance, owned and cleaned up by this object.

    Use as a context manager. Exiting always attempts, in order: close
    the workbook without saving, `Quit()`, release COM references, and —
    only if the owned process is still alive — a targeted terminate.
    """

    def __init__(self, *, startup_timeout_seconds: int = 120, visible: bool = False):
        self.startup_timeout_seconds = startup_timeout_seconds
        self.visible = visible

        self.application: Any = None
        self.workbook: Any = None

        self._pid: int | None = None
        self._create_time: float | None = None
        self._com_initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "ExcelSession":
        self.start()

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        pythoncom, client, _, _ = _win32()

        pythoncom.CoInitialize()
        self._com_initialized = True

        try:
            # DispatchEx, not Dispatch: Dispatch attaches to an existing
            # Excel if one is running, which would put this job inside a
            # user's interactive session and make cleanup unsafe.
            self.application = client.DispatchEx("Excel.Application")
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.EXCEL_LAUNCH_FAILED,
                "Microsoft Excel could not be started.",
                detail={"exception": type(exc).__name__},
            ) from exc

        self._resolve_owned_process()

        try:
            self.application.Visible = self.visible
            # Every one of these exists to stop Excel blocking on a modal
            # dialog in a session with no human to dismiss it.
            self.application.DisplayAlerts = False
            self.application.ScreenUpdating = False
            self.application.EnableEvents = False
            self.application.AskToUpdateLinks = False
            self.application.AlertBeforeOverwriting = False
            # Recovery prompts on the next launch after a crash would
            # otherwise wedge the following execution.
            self.application.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Could not apply all Excel automation settings: {type(exc).__name__}"
            )

        self._await_responsive()

        logger.info(
            f"Excel started (version={self.version}, pid={self._pid})"
        )

    def _resolve_owned_process(self) -> None:
        """Record (pid, create_time) for the instance we just started."""

        _, _, win32process, _ = _win32()

        try:
            _, pid = win32process.GetWindowThreadProcessId(self.application.Hwnd)
            self._pid = int(pid)
        except Exception as exc:  # noqa: BLE001
            # Not fatal — but it does mean forced cleanup is off the
            # table for this session, which the close path honours.
            logger.warning(
                "Could not determine the Excel process id; forced cleanup "
                f"will not be attempted ({type(exc).__name__})."
            )
            self._pid = None

            return

        self._create_time = _process_create_time(self._pid)

    def _await_responsive(self) -> None:
        """Wait until Excel answers COM, or give up with a clear error."""

        deadline = time.monotonic() + self.startup_timeout_seconds
        last_error: str | None = None

        while time.monotonic() < deadline:
            try:
                _ = self.application.Version

                return
            except Exception as exc:  # noqa: BLE001
                last_error = type(exc).__name__
                time.sleep(0.5)

        raise WorkerError(
            WorkerErrorCode.EXCEL_LAUNCH_FAILED,
            "Excel started but did not become responsive.",
            detail={
                "timeout_seconds": self.startup_timeout_seconds,
                "last_error": last_error,
            },
        )

    @property
    def version(self) -> str | None:
        try:
            return str(self.application.Version) if self.application else None
        except Exception:  # noqa: BLE001
            return None

    @property
    def pid(self) -> int | None:
        return self._pid

    # ------------------------------------------------------------------
    # Workbooks
    # ------------------------------------------------------------------

    def open_workbook(self, path: str) -> Any:
        """Open a workbook from an absolute path inside our workspace.

        `UpdateLinks=0` and `ReadOnly=False` are explicit rather than
        defaulted: link updates prompt, and a read-only open would make a
        later save fail in a way that looks like an export bug.
        """

        try:
            self.workbook = self._retry_com(
                lambda: self.application.Workbooks.Open(
                    path,
                    UpdateLinks=0,
                    ReadOnly=False,
                    IgnoreReadOnlyRecommended=True,
                    CorruptLoad=0,
                )
            )
        except WorkerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.WORKBOOK_OPEN_FAILED,
                "Excel could not open the workbook.",
                detail={"exception": type(exc).__name__},
            ) from exc

        return self.workbook

    def save_workbook_as(self, path: str, file_format: int | None = None) -> None:
        if self.workbook is None:
            raise WorkerError(
                WorkerErrorCode.EXPORT_FAILED,
                "No workbook is open to save.",
            )

        try:
            if file_format is None:
                self._retry_com(lambda: self.workbook.SaveAs(path))
            else:
                self._retry_com(
                    lambda: self.workbook.SaveAs(path, FileFormat=file_format)
                )
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.EXPORT_FAILED,
                "The workbook could not be saved.",
                detail={"exception": type(exc).__name__},
            ) from exc

    def export_pdf(self, path: str) -> None:
        if self.workbook is None:
            raise WorkerError(
                WorkerErrorCode.EXPORT_FAILED,
                "No workbook is open to export.",
            )

        try:
            # 0 == xlTypePDF.
            self._retry_com(lambda: self.workbook.ExportAsFixedFormat(0, path))
        except Exception as exc:  # noqa: BLE001
            # Distinguished from EXPORT_FAILED because it is a property of
            # the workbook/host, not a transient problem: a workbook with
            # nothing printable cannot be made to produce a PDF by
            # retrying.
            raise WorkerError(
                WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED,
                "This workbook could not be exported as PDF.",
                detail={"exception": type(exc).__name__},
            ) from exc

    def _retry_com(self, call, attempts: int = 5, delay: float = 1.0):
        """Retry only Excel's "I'm busy" rejections, nothing else.

        A blanket retry would paper over real errors; these two HRESULTs
        specifically mean the call arrived while Excel was mid-operation.
        """

        last: Exception | None = None

        for attempt in range(attempts):
            try:
                return call()
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "hresult", None) or (
                    exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
                )

                if code not in _RPC_RETRY_CODES:
                    raise

                last = exc
                time.sleep(delay * (attempt + 1))

        if last is not None:
            raise last

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Always safe to call, including after a crash mid-session."""

        self._close_workbook()
        self._quit_application()
        self._release_com()
        self._terminate_if_owned_and_alive()

    def _close_workbook(self) -> None:
        if self.workbook is None:
            return

        try:
            # SaveChanges=False: output has already been written to the
            # artifact paths. Saving here could also block on a prompt.
            self.workbook.Close(SaveChanges=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Workbook close failed: {type(exc).__name__}")
        finally:
            self.workbook = None

    def _quit_application(self) -> None:
        if self.application is None:
            return

        try:
            self.application.DisplayAlerts = False
            self.application.Quit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Excel Quit() failed: {type(exc).__name__}")
        finally:
            self.application = None

    def _release_com(self) -> None:
        """Drop references and let COM finish, then uninitialize.

        Without the GC pass, a lingering Python reference to a COM object
        keeps the Excel process alive after Quit() — the classic "ghost
        EXCEL.EXE" that then gets solved by killing everything.
        """

        import gc

        gc.collect()

        if self._com_initialized:
            try:
                pythoncom, _, _, _ = _win32()
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass

            self._com_initialized = False

    def _terminate_if_owned_and_alive(self) -> None:
        """Last resort, narrowly targeted.

        Three conditions must all hold: we know the pid, the process is
        still alive after a graceful Quit and a grace period, and its
        creation time still matches what we recorded. The last check is
        what prevents killing an unrelated process that happens to have
        inherited a recycled pid.
        """

        if self._pid is None:
            return

        deadline = time.monotonic() + 15

        while time.monotonic() < deadline:
            if not _process_alive(self._pid):
                logger.debug(f"Excel pid {self._pid} exited cleanly")

                return

            time.sleep(0.5)

        current_create_time = _process_create_time(self._pid)

        if (
            self._create_time is not None
            and current_create_time is not None
            and abs(current_create_time - self._create_time) > 1.0
        ):
            logger.warning(
                f"Excel pid {self._pid} was recycled by another process; "
                "not terminating."
            )

            return

        if self._create_time is None or current_create_time is None:
            # Ownership unproven. Per the rule at the top of this module,
            # do nothing rather than risk someone else's Excel.
            logger.warning(
                f"Could not confirm ownership of Excel pid {self._pid}; "
                "not terminating. A stale Excel process may remain."
            )

            return

        logger.warning(
            f"Excel pid {self._pid} did not exit after Quit(); terminating "
            "the owned process."
        )

        _terminate(self._pid)


def _process_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass

    try:
        import win32api
        import win32con

        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)

        if not handle:
            return False

        win32api.CloseHandle(handle)

        return True
    except Exception:  # noqa: BLE001
        return False


def _process_create_time(pid: int) -> float | None:
    """Creation time, used to prove a pid still refers to *our* process."""

    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001
        return None


def _terminate(pid: int) -> None:
    try:
        import psutil

        process = psutil.Process(pid)
        process.terminate()

        try:
            process.wait(timeout=10)
        except psutil.TimeoutExpired:
            process.kill()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Could not terminate Excel pid {pid}: {type(exc).__name__}")
