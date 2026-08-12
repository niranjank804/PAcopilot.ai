"""Host probes. A capability is a fact this file established, or absent.

The control plane routes jobs by capability, so a worker that *claims*
PDF_EXPORT without having proved it turns a routing decision into a
runtime failure. Everything reported to the server as a capability comes
from a probe here that actually succeeded on this machine.

Runs the whole probe in one Excel session so a diagnostics call costs one
Excel launch rather than four.
"""

import platform
import socket
from dataclasses import dataclass, field
from typing import Any

from pa_worker import __version__
from pa_worker.logging import get_logger

logger = get_logger("diagnostics")


@dataclass
class HostReport:
    version: str = __version__
    os: str | None = None
    hostname: str | None = None
    excel_version: str | None = None
    pafe_version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_host_facts(self) -> dict[str, Any]:
        """The payload shape the control plane expects."""

        return {
            "version": self.version,
            "os": self.os,
            "hostname": self.hostname,
            "excel_version": self.excel_version,
            "pafe_version": self.pafe_version,
            "capabilities": self.capabilities,
        }


def probe_host(*, deep: bool = True) -> HostReport:
    """Inspect this machine. `deep=False` skips launching Excel."""

    report = HostReport(
        os=f"{platform.system()} {platform.release()}",
        hostname=_hostname(),
    )

    report.checks["python"] = platform.python_version()
    report.checks["platform"] = platform.platform()

    if platform.system() != "Windows":
        report.checks["excel"] = "unavailable (not Windows)"
        report.checks["pafe"] = "unavailable (not Windows)"

        return report

    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401

        report.checks["pywin32"] = "ok"
    except ImportError:
        report.checks["pywin32"] = "missing"
        report.checks["excel"] = "unavailable (pywin32 missing)"
        report.checks["pafe"] = "unavailable (pywin32 missing)"

        return report

    try:
        import psutil  # noqa: F401

        report.checks["psutil"] = "ok"
    except ImportError:
        # Not fatal, but it does disable safe forced cleanup of a hung
        # Excel — worth surfacing rather than discovering during an
        # incident.
        report.checks["psutil"] = (
            "missing (forced Excel cleanup will be unavailable)"
        )

    if not deep:
        return report

    _probe_excel_and_pafe(report)

    return report


def _probe_excel_and_pafe(report: HostReport) -> None:
    """One Excel session; probe Excel, PAfE and PDF export inside it."""

    from pa_worker.excel.session import ExcelSession
    from pa_worker.pafe.automation import PAfEAutomation

    session = ExcelSession(startup_timeout_seconds=120)

    try:
        session.start()
    except Exception as exc:  # noqa: BLE001
        report.checks["excel"] = f"failed ({type(exc).__name__})"

        return

    try:
        report.excel_version = session.version
        report.checks["excel"] = f"ok (version {report.excel_version})"
        report.capabilities.append("excel")
        # Saving .xlsx is intrinsic to a working Excel; no separate probe
        # would tell us anything the launch did not.
        report.capabilities.append("xlsx_export")

        try:
            pafe = PAfEAutomation(session.application)
            pafe.connect()

            report.pafe_version = pafe.version()
            report.checks["pafe"] = f"ok (version {report.pafe_version})"
            report.capabilities.append("pafe_automation")
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            report.checks["pafe"] = (
                f"failed ({code.value if code else type(exc).__name__})"
            )

        if _probe_pdf_export(session):
            report.checks["pdf_export"] = "ok"
            report.capabilities.append("pdf_export")
        else:
            # A very common real condition — no printer driver on a
            # server-class host means Excel cannot render a PDF.
            report.checks["pdf_export"] = (
                "failed (no PDF export; check that a printer driver is "
                "available)"
            )
    finally:
        session.close()


def _probe_pdf_export(session) -> bool:
    """Actually export a throwaway PDF rather than assuming it works."""

    import tempfile
    from pathlib import Path

    try:
        workbook = session.application.Workbooks.Add()
        session.workbook = workbook

        # Needs a printable cell — an empty sheet exports nothing.
        workbook.Sheets(1).Range("A1").Value = "PA-Copilot capability probe"

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "probe.pdf"

            workbook.ExportAsFixedFormat(0, str(target))

            return target.exists() and target.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"PDF probe failed: {type(exc).__name__}")

        return False
    finally:
        try:
            if session.workbook is not None:
                session.workbook.Close(SaveChanges=False)
                session.workbook = None
        except Exception:  # noqa: BLE001
            pass


def _hostname() -> str | None:
    try:
        return socket.gethostname()[:100]
    except OSError:
        return None
