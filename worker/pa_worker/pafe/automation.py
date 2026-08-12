"""IBM Planning Analytics for Microsoft Excel automation.

Every method here maps 1:1 onto an API IBM documents. The reference used
is the PAx API documentation's own source, which is the authoritative
description of the COM surface:

    https://ibm.github.io/paxapi/
    https://github.com/IBM/paxapi/blob/master/source/includes/globalapi.md

Verified signatures used by this module:

    Logon(url, username, password, namespace) -> Boolean
    LogonSSO(serverURL, namespace, hideForm, bypassPAWChooser) -> Boolean
    Logoff()
    RefreshAllData()
    RefreshBook()
    RefreshSheet()
    Wait()
    TraceLog() -> String
    TraceError(message)
    SuppressMessages(bool)
    UserAgent -> String                (e.g. "PAfE/2.0.66.9 (...); Excel/16.0...")
    UserAgentSCReleaseFull -> String   (e.g. "2.0.66.9")

The automation object is reached through the COM add-in, exactly as IBM
documents:

    Application.COMAddIns("CognosOffice12.Connect").Object.AutomationServer
        .Application("COR", "1.1")

IBM notes there is no type library on the client, so this is necessarily
late-bound — there is no way to get IntelliSense or compile-time
checking, which is why every call here is wrapped and classified.

Two things this module deliberately does NOT do:

1. **It does not import or run the IBM .bas/.cls macro modules.** Those
   exist so that a *human* writing VBA inside a workbook gets a
   convenient `CognosOfficeAutomationObject` helper. Calling the COM
   object directly from Python reaches the same documented API without
   ever executing VBA — which is what keeps "no arbitrary VBA execution"
   true rather than merely intended.

2. **It does not sleep to wait for a refresh.** `Wait()` is IBM's
   documented completion mechanism ("Holds VBA thread until background
   tasks complete") and is what this module calls. Because `Wait()`
   blocks the calling thread and cannot be cancelled from inside the
   process, the timeout is enforced by the *parent* process killing this
   one — see `pa_worker/execution/supervisor.py`.
"""

from typing import Any

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.logging import get_logger

logger = get_logger("pafe")

# The COM add-in ProgID IBM documents for PAfE / Cognos Office.
ADDIN_PROGID = "CognosOffice12.Connect"

# IBM's documented arguments for retrieving the Reporting application
# object from the automation server.
_APPLICATION_ID = "COR"
_APPLICATION_VERSION = "1.1"

# Signals in a TraceLog that indicate the refresh did not really work.
# Ordered most specific first; the first match decides the classification.
_TRACE_FAILURE_SIGNALS: tuple[tuple[str, WorkerErrorCode], ...] = (
    ("could not log on", WorkerErrorCode.TM1_AUTH_FAILED),
    ("logon failed", WorkerErrorCode.TM1_AUTH_FAILED),
    ("authentication failed", WorkerErrorCode.TM1_AUTH_FAILED),
    ("unauthorized", WorkerErrorCode.TM1_AUTH_FAILED),
    ("invalid credentials", WorkerErrorCode.TM1_AUTH_FAILED),
    ("unable to connect", WorkerErrorCode.TM1_CONNECTION_FAILED),
    ("connection refused", WorkerErrorCode.TM1_CONNECTION_FAILED),
    ("server not available", WorkerErrorCode.TM1_CONNECTION_FAILED),
    ("no connection", WorkerErrorCode.TM1_CONNECTION_FAILED),
    ("timed out", WorkerErrorCode.TM1_CONNECTION_FAILED),
)


def pafe_available(excel_application: Any) -> tuple[bool, str | None]:
    """Probe for the PAfE add-in and its automation object.

    Returns (available, version). Used by `pa-worker diagnostics` and at
    enrollment so the worker only ever claims PAFE_AUTOMATION on a host
    where the object actually resolved — a capability is a verified fact
    here, not a configuration setting.
    """

    try:
        automation = PAfEAutomation(excel_application)
        automation.connect()

        return True, automation.version()
    except WorkerError as exc:
        logger.debug(f"PAfE probe failed: {exc.code.value}")

        return False, None
    except Exception as exc:  # noqa: BLE001 - a probe must never raise
        logger.debug(f"PAfE probe failed: {type(exc).__name__}")

        return False, None


class PAfEAutomation:
    """Thin, allowlisted wrapper over the IBM automation object."""

    def __init__(self, excel_application: Any):
        self.excel = excel_application
        self.reporting: Any = None
        self._logged_on = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def connect(self) -> Any:
        """Resolve the IBM automation object, or classify why we can't.

        The three failure modes are genuinely different and an operator
        needs to be able to tell them apart: the add-in is not installed,
        it is installed but disabled, or it is loaded but not exposing
        the automation server.
        """

        try:
            addin = self.excel.COMAddIns(ADDIN_PROGID)
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.PAFE_NOT_INSTALLED,
                "The Planning Analytics for Microsoft Excel COM add-in "
                f"('{ADDIN_PROGID}') is not registered with Excel.",
                detail={"exception": type(exc).__name__},
            ) from exc

        try:
            if not addin.Connect:
                # Loading it here rather than failing means a host where
                # the add-in is merely inactive still works unattended.
                logger.info("PAfE add-in was inactive; connecting it")
                addin.Connect = True
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.PAFE_API_UNAVAILABLE,
                "The PAfE add-in is registered but could not be activated.",
                detail={"exception": type(exc).__name__},
            ) from exc

        try:
            automation_server = addin.Object.AutomationServer
            self.reporting = automation_server.Application(
                _APPLICATION_ID, _APPLICATION_VERSION
            )
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.PAFE_API_UNAVAILABLE,
                "The PAfE add-in is active but did not expose its "
                "automation object.",
                detail={"exception": type(exc).__name__},
            ) from exc

        if self.reporting is None:
            raise WorkerError(
                WorkerErrorCode.PAFE_API_UNAVAILABLE,
                "The PAfE automation object resolved to nothing.",
            )

        return self.reporting

    def version(self) -> str | None:
        """PAfE build, via IBM's documented UserAgent properties."""

        for attribute in ("UserAgentSCReleaseFull", "UserAgent"):
            try:
                value = getattr(self.reporting, attribute)

                if value:
                    return str(value)[:50]
            except Exception:  # noqa: BLE001
                continue

        return None

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def suppress_messages(self, suppress: bool = True) -> None:
        """IBM: SuppressMessages(). Stops modal dialogs blocking a run.

        Best-effort: a host where this is unavailable can still refresh,
        it is just more likely to stall on a prompt — and the parent
        process's timeout is what catches that.
        """

        try:
            self.reporting.SuppressMessages(suppress)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"PAfE SuppressMessages() unavailable: {type(exc).__name__}"
            )

    def logon(
        self,
        *,
        url: str,
        username: str,
        password: str,
        namespace: str,
    ) -> None:
        """IBM: Logon(url, username, password, namespace) -> Boolean.

        IBM documents that this **cannot log in to cloud-based systems**.
        The worker therefore treats Logon as optional and only calls it
        when the operator has explicitly configured local credentials for
        a connection; otherwise the workbook refreshes against whatever
        PAfE session already exists on the machine. See the
        authentication support matrix in docs/report-automation/README.md.

        Credentials come from the worker's own local credential store.
        They are never sent by the control plane and never logged.
        """

        try:
            result = self.reporting.Logon(url, username, password, namespace)
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.TM1_CONNECTION_FAILED,
                "The PAfE Logon call failed.",
                detail={"exception": type(exc).__name__},
            ) from exc

        if not result:
            # IBM returns False for a rejected sign-in rather than
            # raising, so a falsy return is the auth failure signal.
            raise WorkerError(
                WorkerErrorCode.TM1_AUTH_FAILED,
                "Planning Analytics rejected the sign-in.",
                # Nothing identifying: no url, no username, no namespace.
                detail={"logon_returned": False},
            )

        self._logged_on = True

        logger.info("PAfE Logon succeeded")

    def logoff(self) -> None:
        """IBM: Logoff(). Best-effort — never masks a real failure."""

        if not self._logged_on:
            return

        try:
            self.reporting.Logoff()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PAfE Logoff() failed: {type(exc).__name__}")
        finally:
            self._logged_on = False

    # ------------------------------------------------------------------
    # Refresh — the operation this POC exists to prove
    # ------------------------------------------------------------------

    def refresh_all_data(self) -> None:
        """IBM: RefreshAllData(). Refreshes every report in the workbook."""

        try:
            self.reporting.RefreshAllData()
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.REFRESH_FAILED,
                "The PAfE RefreshAllData call failed.",
                detail={"exception": type(exc).__name__},
            ) from exc

    def refresh_book(self) -> None:
        """IBM: RefreshBook(). Refreshes data in the open workbooks."""

        try:
            self.reporting.RefreshBook()
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.REFRESH_FAILED,
                "The PAfE RefreshBook call failed.",
                detail={"exception": type(exc).__name__},
            ) from exc

    def wait(self) -> None:
        """IBM: Wait(). "Holds VBA thread until background tasks complete."

        This is the documented completion mechanism and the reason this
        worker contains no polling sleep for refresh completion.

        It blocks and offers no cancellation, so an unresponsive TM1
        server means this call never returns. That is handled one level
        up: the whole Excel session runs in a child process which the
        parent kills when the execution's timeout expires
        (`pa_worker/execution/supervisor.py`). Enforcing a timeout around
        an uncancellable blocking COM call is not possible inside the
        process making it.
        """

        try:
            self.reporting.Wait()
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(
                WorkerErrorCode.REFRESH_FAILED,
                "The PAfE Wait call failed while waiting for the refresh "
                "to complete.",
                detail={"exception": type(exc).__name__},
            ) from exc

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def trace_log(self) -> str | None:
        """IBM: TraceLog() -> String. Automation activity and errors.

        Never fatal if unavailable — losing the diagnostic log must not
        turn a successful refresh into a failed report.
        """

        try:
            value = self.reporting.TraceLog

            # Documented as a property returning String, but late binding
            # can surface it as a callable depending on the build.
            if callable(value):
                value = value()

            return str(value) if value else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PAfE TraceLog() unavailable: {type(exc).__name__}")

            return None

    def trace_error(self, message: str) -> None:
        """IBM: TraceError(message). Annotates IBM's own log."""

        try:
            self.reporting.TraceError(message)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"PAfE TraceError() unavailable: {type(exc).__name__}")

    @staticmethod
    def classify_trace_log(trace: str | None) -> WorkerError | None:
        """Turn a TraceLog into a failure, if it describes one.

        This matters because `RefreshAllData()` returning without raising
        does not by itself mean data arrived — PAfE reports connection
        and authentication problems into the trace log while the COM call
        completes normally. Without this check a report whose refresh
        silently failed would be uploaded as a success, which is the
        worst possible outcome: a stale report that looks current.
        """

        if not trace:
            return None

        lowered = trace.lower()

        for signal, code in _TRACE_FAILURE_SIGNALS:
            if signal in lowered:
                return WorkerError(
                    code,
                    "The PAfE automation log reported a failure during "
                    "refresh.",
                    detail={"trace_signal": signal},
                )

        return None
