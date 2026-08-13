"""Layer-by-layer PAfE probe with an explicit, non-guessable verdict.

The failure this exists to prevent: reporting "PAfE supported" because
Excel launched. Excel is necessary and nowhere near sufficient — the
add-in can be absent, present-but-unregistered, registered-but-disabled,
or loaded but not exposing the automation object. Those need different
fixes, so they get different verdicts.

Each layer is probed independently and the verdict is derived from how
far the chain actually got, never inferred from an adjacent signal.
"""

import os
import platform
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pa_worker.logging import get_logger
from pa_worker.pafe.automation import (
    ADDIN_PROGID,
    _APPLICATION_ID,
    _APPLICATION_VERSION,
)

logger = get_logger("pafe.probe")

#: Every ProgID PAfE has been observed or documented to register under.
#: `ADDIN_PROGID` (CognosOffice12.Connect) is the one IBM's automation
#: documentation names and the one the automation path uses; the others
#: are checked so that "not installed" is a conclusion drawn from all
#: known names rather than from one.
KNOWN_PAFE_PROGIDS: tuple[str, ...] = (
    ADDIN_PROGID,
    "CognosOffice12.ConnectPAfEAddin",
    "CognosOffice12.ConnectPAfE",
    "CognosOfficePAfE.Connect",
)


class PAfEStatus(str, Enum):
    """Deliberately four states, not a boolean.

    "Installed but unavailable" is the most common real-world case and
    the one a boolean hides — the add-in is present, so the customer
    believes it works, but Excel has it disabled or it failed to load.
    """

    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED_BUT_UNAVAILABLE = "INSTALLED_BUT_UNAVAILABLE"
    INSTALLED_AND_AUTOMATION_AVAILABLE = "INSTALLED_AND_AUTOMATION_AVAILABLE"
    UNKNOWN = "UNKNOWN"


class PAfEFailure(str, Enum):
    """Precisely which link in the chain broke.

    `PAfEStatus` answers "can this host run jobs"; this answers "what do
    I fix". They are separate because the same status has several
    different remedies — Excel missing, add-in never installed, add-in
    installed but unregistered, and COM refusing to hand over the
    automation object are four different afternoons of work.
    """

    EXCEL_NOT_INSTALLED = "EXCEL_NOT_INSTALLED"
    PAFE_NOT_INSTALLED = "PAFE_NOT_INSTALLED"
    PAFE_ADDIN_NOT_REGISTERED = "PAFE_ADDIN_NOT_REGISTERED"
    PAFE_COM_UNAVAILABLE = "PAFE_COM_UNAVAILABLE"
    AUTOMATION_SERVER_UNAVAILABLE = "AUTOMATION_SERVER_UNAVAILABLE"
    PAFE_READY = "PAFE_READY"


@dataclass
class PAfEProbeResult:
    status: PAfEStatus = PAfEStatus.UNKNOWN

    windows_version: str | None = None
    python_version: str | None = None
    excel_version: str | None = None
    pafe_version: str | None = None

    # Each layer of the documented COM access path, probed separately.
    com_addin_registered: bool | None = None
    com_addin_connected: bool | None = None
    automation_server_available: bool | None = None
    application_object_available: bool | None = None
    trace_log_accessible: bool | None = None

    # Evidence gathered outside COM, so "not installed" is a conclusion
    # rather than one failed call.
    registry_progid_found: bool | None = None
    registered_progids: tuple[str, ...] = ()
    install_directory: str | None = None

    #: Which link in the chain broke — see PAfEFailure.
    failure: "PAfEFailure | None" = None

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "windows_version": self.windows_version,
            "python_version": self.python_version,
            "excel_version": self.excel_version,
            "pafe_version": self.pafe_version,
            "failure": self.failure.value if self.failure else None,
            "registered_progids": list(self.registered_progids),
            "com_addin_registered": self.com_addin_registered,
            "com_addin_connected": self.com_addin_connected,
            "automation_server_available": self.automation_server_available,
            "application_object_available": self.application_object_available,
            "trace_log_accessible": self.trace_log_accessible,
            "registry_progid_found": self.registry_progid_found,
            "install_directory": self.install_directory,
            "notes": self.notes,
        }


# IBM's documented client install location (PAx API "Set up" section).
_INSTALL_CANDIDATES = (
    r"C:\Program Files\ibm\cognos\IBM for Microsoft Office",
    r"C:\Program Files (x86)\ibm\cognos\IBM for Microsoft Office",
)


def _probe_registry(result: PAfEProbeResult) -> None:
    """Is any known PAfE COM class registered?

    Independent of Excel: it distinguishes "never installed" from
    "installed but Excel will not load it", which is the difference
    between an install task and a configuration task.

    Checks **every** known ProgID variant, not just the one the
    automation path uses. PAfE has shipped under more than one class
    name across releases, so reporting NOT_INSTALLED after testing a
    single ProgID would misdiagnose a host where PAfE is present under
    the other name — an install task raised against a machine that
    only needed the add-in re-registering.
    """

    if os.name != "nt":
        result.registry_progid_found = None

        return

    try:
        import winreg
    except ImportError:
        result.registry_progid_found = None

        return

    found: list[str] = []
    checked_cleanly = True

    for progid in KNOWN_PAFE_PROGIDS:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid):
                found.append(progid)
        except FileNotFoundError:
            continue
        except OSError as exc:
            checked_cleanly = False
            result.notes.append(
                f"Registry probe for {progid} failed: {type(exc).__name__}"
            )

    result.registered_progids = tuple(found)

    if found:
        result.registry_progid_found = True

        if ADDIN_PROGID not in found:
            # Present, but not under the name the automation path uses.
            result.notes.append(
                f"PAfE is registered as {found[0]}, but the automation "
                f"ProgID '{ADDIN_PROGID}' is absent. The add-in may need "
                "re-registering."
            )
    elif checked_cleanly:
        result.registry_progid_found = False
    else:
        # Some probe errored, so absence is not established.
        result.registry_progid_found = None

    for candidate in _INSTALL_CANDIDATES:
        if os.path.isdir(candidate):
            result.install_directory = candidate

            break


def _probe_com(result: PAfEProbeResult, excel_application: Any) -> None:
    """Walk the documented COM path one hop at a time.

    Deliberately not `PAfEAutomation.connect()`: that returns a single
    classified error, which is right for an execution but wrong for a
    diagnostic. Here each hop is recorded so an operator can see exactly
    where the chain broke.
    """

    try:
        addin = excel_application.COMAddIns(ADDIN_PROGID)
        result.com_addin_registered = True
    except Exception as exc:  # noqa: BLE001
        result.com_addin_registered = False
        result.notes.append(
            f"Excel does not know the add-in '{ADDIN_PROGID}' "
            f"({type(exc).__name__})."
        )

        return

    try:
        connected = bool(addin.Connect)

        if not connected:
            # Try to activate it — a merely-inactive add-in is a
            # configuration problem the worker can fix itself.
            addin.Connect = True
            connected = bool(addin.Connect)
            result.notes.append(
                "The add-in was inactive and was activated by this probe."
            )

        result.com_addin_connected = connected
    except Exception as exc:  # noqa: BLE001
        result.com_addin_connected = False
        result.notes.append(
            f"The add-in could not be activated ({type(exc).__name__})."
        )

        return

    try:
        automation_server = addin.Object.AutomationServer
        result.automation_server_available = automation_server is not None
    except Exception as exc:  # noqa: BLE001
        result.automation_server_available = False
        result.notes.append(
            f"AutomationServer not exposed ({type(exc).__name__})."
        )

        return

    try:
        reporting = automation_server.Application(
            _APPLICATION_ID, _APPLICATION_VERSION
        )
        result.application_object_available = reporting is not None
    except Exception as exc:  # noqa: BLE001
        result.application_object_available = False
        result.notes.append(
            f'Application("{_APPLICATION_ID}", "{_APPLICATION_VERSION}") '
            f"not accessible ({type(exc).__name__})."
        )

        return

    for attribute in ("UserAgentSCReleaseFull", "UserAgent"):
        try:
            value = getattr(reporting, attribute)

            if value:
                result.pafe_version = str(value)[:50]

                break
        except Exception:  # noqa: BLE001
            continue

    try:
        value = reporting.TraceLog

        if callable(value):
            value = value()

        # Accessible even when empty — presence of the property is what
        # is being established, not its content.
        result.trace_log_accessible = True
    except Exception as exc:  # noqa: BLE001
        result.trace_log_accessible = False
        result.notes.append(
            f"TraceLog not accessible ({type(exc).__name__})."
        )


def _derive_status(result: PAfEProbeResult) -> PAfEStatus:
    """The verdict, from evidence only.

    Never returns AVAILABLE on the strength of Excel being present, and
    never returns NOT_INSTALLED when the COM probe could not run at all
    (that is UNKNOWN — absence of evidence is not evidence of absence).
    """

    if result.application_object_available:
        return PAfEStatus.INSTALLED_AND_AUTOMATION_AVAILABLE

    # Any layer positively answering means something is installed; the
    # chain just did not complete.
    partial = any(
        (
            result.com_addin_registered,
            result.com_addin_connected,
            result.automation_server_available,
            result.registry_progid_found,
            result.install_directory is not None,
        )
    )

    if partial:
        return PAfEStatus.INSTALLED_BUT_UNAVAILABLE

    # Both independent checks ran and both said no.
    if result.com_addin_registered is False and result.registry_progid_found is False:
        return PAfEStatus.NOT_INSTALLED

    return PAfEStatus.UNKNOWN


def _derive_failure(result: PAfEProbeResult) -> PAfEFailure | None:
    """Which link broke, walked in the order an operator would fix them.

    Excel first: without it nothing downstream can be judged, and
    reporting PAFE_NOT_INSTALLED on a host that simply has no Excel
    sends someone to install the wrong product.
    """

    if result.application_object_available:
        return PAfEFailure.PAFE_READY

    if not result.excel_version:
        return PAfEFailure.EXCEL_NOT_INSTALLED

    # Registered somewhere, but not under the automation ProgID Excel
    # was asked for — a re-registration problem, not an install one.
    if (
        result.registry_progid_found
        and result.registered_progids
        and ADDIN_PROGID not in result.registered_progids
    ):
        return PAfEFailure.PAFE_ADDIN_NOT_REGISTERED

    if result.registry_progid_found is False and not result.com_addin_registered:
        return PAfEFailure.PAFE_NOT_INSTALLED

    if result.com_addin_registered is False:
        return PAfEFailure.PAFE_ADDIN_NOT_REGISTERED

    if result.com_addin_connected is False:
        return PAfEFailure.PAFE_COM_UNAVAILABLE

    if result.automation_server_available is False:
        return PAfEFailure.AUTOMATION_SERVER_UNAVAILABLE

    return None


def probe_pafe(*, excel_startup_timeout_seconds: int = 120) -> PAfEProbeResult:
    """Full PAfE probe. Launches Excel, and always closes it."""

    result = PAfEProbeResult(
        windows_version=f"{platform.system()} {platform.release()} "
        f"({platform.version()})",
        python_version=platform.python_version(),
    )

    _probe_registry(result)

    if platform.system() != "Windows":
        result.notes.append("Not Windows — COM automation is unavailable.")
        result.status = PAfEStatus.UNKNOWN
        result.failure = PAfEFailure.EXCEL_NOT_INSTALLED

        return result

    try:
        from pa_worker.excel.session import ExcelSession
    except Exception as exc:  # noqa: BLE001
        result.notes.append(f"Cannot import the Excel session ({type(exc).__name__}).")
        result.status = _derive_status(result)
        result.failure = _derive_failure(result)

        return result

    session = ExcelSession(
        startup_timeout_seconds=excel_startup_timeout_seconds
    )

    try:
        session.start()
        result.excel_version = session.version
    except Exception as exc:  # noqa: BLE001
        # Excel itself failed, so nothing can be concluded about PAfE.
        result.notes.append(
            f"Excel could not be started ({type(exc).__name__}); PAfE could "
            "not be probed through COM."
        )
        result.status = _derive_status(result)
        result.failure = _derive_failure(result)

        return result

    try:
        _probe_com(result, session.application)
    finally:
        session.close()

    result.status = _derive_status(result)
    result.failure = _derive_failure(result)

    return result
