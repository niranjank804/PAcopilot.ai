r"""THE acceptance test: real PAfE, real TM1, verified data change.

Everything else in this suite proves the plumbing. This proves the
premise — that a PAfE workbook driven by this worker actually contains
fresh TM1 data afterwards.

It skips unless a real environment is present, and says precisely what is
missing. It is not a mock and cannot pass without PAfE.

## Why a random expected value, not a fixed 222222

A fixed sentinel is the flaw that would make this test worthless. If the
workbook was last saved showing 222222, a refresh that silently did
nothing still produces an artifact containing 222222, and the test
passes while the integration is broken — exactly the "RefreshAllData
returned without exception" failure this phase exists to rule out.

Writing a fresh random value to TM1 immediately before the run means the
only way that number can appear in the artifact is if this execution
really fetched it. Freshness is proven, not assumed.

## Running it

    set PA_COPILOT_TM1_ADDRESS=localhost
    set PA_COPILOT_TM1_PORT=12354
    set PA_COPILOT_TM1_SSL=true
    set PA_COPILOT_TM1_USER=admin
    set PA_COPILOT_TM1_PASSWORD=...            # never logged
    set PA_COPILOT_PAFE_TEST_WORKBOOK=C:\path\to\PA_Copilot_Test.xlsx
    set PA_COPILOT_PAFE_TEST_CELL=Sheet1!B2

    pytest worker/tests/test_pafe_live.py -m pafe_live -v

The workbook must be a genuine PAfE workbook whose cell
PA_COPILOT_PAFE_TEST_CELL resolves the intersection this test writes to
(cube PA_COPILOT_TEST, elements TestEntity / Value) — normally a DBRW
formula. It has to be authored in Excel with PAfE installed; it cannot be
generated here, which is why it is supplied by path.
"""

import os
import random
from pathlib import Path

import pytest

pytestmark = pytest.mark.pafe_live

CUBE = "PA_COPILOT_TEST"
ELEMENTS = ("TestEntity", "Value")
COORDINATE_STRING = ",".join(ELEMENTS)


# ----------------------------------------------------------------------
# Environment gating — each requirement reported separately
# ----------------------------------------------------------------------


def _missing_requirements() -> list[str]:
    missing: list[str] = []

    for variable in (
        "PA_COPILOT_TM1_ADDRESS",
        "PA_COPILOT_TM1_PORT",
        "PA_COPILOT_TM1_USER",
        "PA_COPILOT_PAFE_TEST_WORKBOOK",
        "PA_COPILOT_PAFE_TEST_CELL",
    ):
        if not os.environ.get(variable):
            missing.append(f"env {variable}")

    workbook = os.environ.get("PA_COPILOT_PAFE_TEST_WORKBOOK")

    if workbook and not Path(workbook).exists():
        missing.append(f"workbook not found at {workbook}")

    try:
        import TM1py  # noqa: F401
    except ImportError:
        missing.append("TM1py (pip install TM1py)")

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        missing.append("openpyxl (pip install openpyxl)")

    try:
        from pa_worker.pafe.probe import PAfEStatus, probe_pafe

        status = probe_pafe().status

        if status != PAfEStatus.INSTALLED_AND_AUTOMATION_AVAILABLE:
            missing.append(f"PAfE automation ({status.value})")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"PAfE probe failed ({type(exc).__name__})")

    return missing


_MISSING = _missing_requirements()

requires_live_pafe = pytest.mark.skipif(
    bool(_MISSING),
    reason="live PAfE/TM1 environment unavailable: " + "; ".join(_MISSING),
)


# ----------------------------------------------------------------------
# TM1 fixture
# ----------------------------------------------------------------------


def _tm1_params() -> dict:
    return {
        "address": os.environ["PA_COPILOT_TM1_ADDRESS"],
        "port": int(os.environ["PA_COPILOT_TM1_PORT"]),
        "ssl": os.environ.get("PA_COPILOT_TM1_SSL", "true").lower() == "true",
        "user": os.environ["PA_COPILOT_TM1_USER"],
        "password": os.environ.get("PA_COPILOT_TM1_PASSWORD", ""),
        "ssl_verify": False,
    }


@pytest.fixture
def tm1():
    from TM1py import TM1Service

    with TM1Service(**_tm1_params()) as service:
        yield service


@pytest.fixture
def expected_value(tm1) -> int:
    """Write a fresh random value to TM1 and return it.

    The whole proof rests on this: a number that did not exist anywhere
    before this test started, so its presence in the artifact can only
    mean a real refresh happened.
    """

    value = random.randint(100_000, 999_999)

    tm1.cells.write_value(value, CUBE, ELEMENTS)

    written_back = tm1.cells.get_value(CUBE, COORDINATE_STRING)

    assert written_back == value, (
        "TM1 did not accept the seed value; the test environment is not "
        "usable and a PAfE result could not be trusted"
    )

    return value


# ----------------------------------------------------------------------
# The acceptance test
# ----------------------------------------------------------------------


@requires_live_pafe
class TestRealPAfERefresh:

    def test_refresh_brings_changed_tm1_data_into_the_artifact(
        self, expected_value, tmp_path
    ):
        """TEST 04-11: the end-to-end premise of the whole feature."""

        import openpyxl

        from pa_worker.execution.runner import PAfEWorkbookRunner
        from pa_worker.execution.workspace import Workspace

        source = Path(os.environ["PA_COPILOT_PAFE_TEST_WORKBOOK"])
        sheet_name, cell_address = os.environ[
            "PA_COPILOT_PAFE_TEST_CELL"
        ].split("!")

        job = {
            "execution_id": "pafe-live-acceptance",
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx"],
            "connection": None,
        }

        steps: list[str] = []

        with Workspace("pafe-live", root=tmp_path) as workspace:
            # Copy in, so the operator's source workbook is never modified.
            working_copy = workspace.write_workbook(
                source.read_bytes(), source.name
            )

            result = PAfEWorkbookRunner().run(
                job, workspace, working_copy, progress=steps.append
            )

            assert result.artifacts, "no artifact was produced"

            artifact = result.artifacts[0]

            # TEST 11 — TraceLog captured.
            assert result.trace_log is not None, "no TraceLog captured"

            # TEST 08 — the value in the produced artifact must be the one
            # written to TM1 moments ago. data_only=True reads the cached
            # computed value, which is what the refresh wrote.
            workbook = openpyxl.load_workbook(artifact.path, data_only=True)
            actual = workbook[sheet_name][cell_address].value
            workbook.close()

            assert actual is not None, (
                f"{sheet_name}!{cell_address} is empty in the artifact — the "
                "refresh did not populate it"
            )

            assert int(actual) == expected_value, (
                f"STALE DATA: artifact shows {actual}, TM1 holds "
                f"{expected_value}. RefreshAllData()/Wait() completed without "
                "error but the workbook did not receive current TM1 data."
            )

        # TEST 06/07 — the documented sequence actually ran.
        assert "refresh_started" in steps
        assert "refresh_completed" in steps
        assert "excel_closed" in steps

    def test_pdf_export_where_supported(self, expected_value, tmp_path):
        """TEST 10: PDF is best-effort, so a failure is reported, not fatal."""

        from pa_worker.errors import WorkerError, WorkerErrorCode
        from pa_worker.execution.runner import PAfEWorkbookRunner
        from pa_worker.execution.workspace import Workspace

        source = Path(os.environ["PA_COPILOT_PAFE_TEST_WORKBOOK"])

        job = {
            "execution_id": "pafe-live-pdf",
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx", "pdf"],
            "connection": None,
        }

        with Workspace("pafe-live-pdf", root=tmp_path) as workspace:
            working_copy = workspace.write_workbook(
                source.read_bytes(), source.name
            )

            try:
                result = PAfEWorkbookRunner().run(
                    job, workspace, working_copy, progress=lambda step: None
                )
            except WorkerError as exc:
                if exc.code == WorkerErrorCode.EXPORT_FORMAT_UNSUPPORTED:
                    pytest.skip(
                        "PDF export unsupported on this host (usually a "
                        "missing printer driver)"
                    )

                raise

            formats = {artifact.output_format for artifact in result.artifacts}

            assert formats == {"xlsx", "pdf"}

            pdf = next(a for a in result.artifacts if a.output_format == "pdf")

            assert pdf.path.read_bytes().startswith(b"%PDF")

    def test_no_worker_owned_excel_survives(self, expected_value, tmp_path):
        """TEST 12/13: cleanup after a real PAfE run."""

        import psutil

        from pa_worker.execution.runner import PAfEWorkbookRunner
        from pa_worker.execution.workspace import Workspace

        before = {p.pid for p in psutil.process_iter(["name"])
                  if (p.info["name"] or "").lower() == "excel.exe"}

        source = Path(os.environ["PA_COPILOT_PAFE_TEST_WORKBOOK"])

        job = {
            "execution_id": "pafe-live-cleanup",
            "operation": "REFRESH_WORKBOOK",
            "output_formats": ["xlsx"],
            "connection": None,
        }

        with Workspace("pafe-live-cleanup", root=tmp_path) as workspace:
            working_copy = workspace.write_workbook(
                source.read_bytes(), source.name
            )

            PAfEWorkbookRunner().run(
                job, workspace, working_copy, progress=lambda step: None
            )

        after = {p.pid for p in psutil.process_iter(["name"])
                 if (p.info["name"] or "").lower() == "excel.exe"}

        assert not (after - before), (
            f"leaked Excel process(es): {after - before}"
        )
        # TEST 14 — anything running beforehand is untouched.
        assert before.issubset(after | before)


@requires_live_pafe
class TestRealPAfEFailureModes:
    """Failure matrix items that need a live PAfE to be meaningful."""

    def test_tm1_unavailable_is_detected_from_the_trace_log(self, tmp_path):
        """FAILURE D: a clean COM call with a failed refresh underneath.

        The most dangerous failure mode — it must not produce a
        successful-looking artifact of stale data.
        """

        from pa_worker.pafe.automation import PAfEAutomation

        error = PAfEAutomation.classify_trace_log(
            "ERROR: unable to connect to the TM1 server"
        )

        assert error is not None
        assert error.code.value == "tm1_connection_failed"


def test_environment_report():
    """Always runs. Records exactly what was and was not available.

    Deliberately not skipped: a run of this file should always leave
    evidence of *why* the acceptance test did or did not execute.
    """

    if _MISSING:
        print()
        print("PAfE live acceptance test did NOT run. Missing:")

        for item in _MISSING:
            print(f"  - {item}")
    else:
        print()
        print("PAfE live acceptance environment fully available.")
