"""The allowlist of things a worker can be told to do.

This is a security boundary, not a convenience enum.

The control plane sends a worker a *verb* from this list plus typed,
validated parameters. It never sends code, a macro name, a command line,
a file path, or anything else the worker could be induced to execute.
The worker, in turn, refuses any operation it does not have a hard-coded
handler for. Both halves are required: an allowlist that only one side
enforces is a convention, not a control.

Concretely, this closes:

* **VBA injection.** There is no field, anywhere in the job payload, that
  reaches a `Application.Run` call or a VBA module. The worker calls
  fixed COM methods on the IBM automation object; the payload chooses
  *which fixed method*, never *what code*.
* **Command injection.** The worker never builds a shell command from
  payload data, and never passes payload data as a process argument.
* **AI-authored commands.** When AI report drafting lands (Phase 7), the
  model can only ever propose a member of this enum. A model that
  hallucinates `EXECUTE_SCRIPT` produces a validation error, not an
  execution.

Adding a member here is a deliberate act that requires a matching
handler on the worker and a review of what that handler can be made to
do with attacker-influenced parameters.
"""

from enum import Enum

from src.core.exceptions import ValidationException
from src.database.models.report_definition import ReportDefinition
from src.reports.enums import ReportType


class WorkerOperation(str, Enum):
    """Operations a worker may be asked to perform.

    Only REFRESH_WORKBOOK is implemented, on both sides. The others are
    named here to document the intended shape of the allowlist, and are
    NOT dispatched by `operation_for_report()` — a worker receiving one
    today would reject it.
    """

    # Implemented: open the workbook, RefreshAllData(), Wait(), export.
    REFRESH_WORKBOOK = "REFRESH_WORKBOOK"

    # Reserved — no worker handler exists yet.
    REFRESH_SHEET = "REFRESH_SHEET"
    EXPORT_XLSX = "EXPORT_XLSX"
    EXPORT_PDF = "EXPORT_PDF"


IMPLEMENTED_OPERATIONS = frozenset({WorkerOperation.REFRESH_WORKBOOK})


def operation_for_report(report: ReportDefinition) -> WorkerOperation:
    """Choose the operation from the report's type — server-side only.

    Note what this function does *not* do: it does not read an operation
    out of `report.parameters`, or out of any request body. The operation
    is derived from a validated enum column, so no user-supplied value
    can select it, let alone invent one.
    """

    if report.report_type == ReportType.PAFE_WORKBOOK.value:
        return WorkerOperation.REFRESH_WORKBOOK

    raise ValidationException(
        f"No worker operation is implemented for report type "
        f"'{report.report_type}'."
    )
