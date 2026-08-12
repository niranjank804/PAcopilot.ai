"""Input validation for things that later become files on a Windows box.

The threat this module exists for: an uploaded "workbook" is downloaded
by a worker, written to disk, and opened by Excel. A filename is
therefore not a label — it is a path fragment and an Excel instruction.
Everything here treats it as hostile input.
"""

import hashlib
import re
import unicodedata

from src.core.exceptions import ValidationException
from src.reports.enums import OutputFormat, ReportType, IMPLEMENTED_REPORT_TYPES

# PAfE workbooks are OOXML: .xlsx (no macros), .xlsm (the common case —
# the IBM automation .bas/.cls modules live in a macro-enabled workbook),
# .xlsb (binary OOXML). Legacy OLE2 .xls is deliberately excluded: it is a
# different container format with a much worse parser history, and PAfE
# targets modern Excel.
ALLOWED_WORKBOOK_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".xlsb"})

# All three allowed extensions are ZIP containers.
_ZIP_MAGIC = b"PK\x03\x04"
# Legacy .xls / OLE2 compound document, matched only to give a specific
# error instead of the generic "not a workbook".
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._&()\-]{0,127}$")

MAX_FILENAME_LENGTH = 128


def sanitize_filename(raw: str) -> str:
    """Reduce a user-supplied name to something safe to display and store.

    This does not produce the name the worker writes to disk — the worker
    names files after the workbook's UUID precisely so that this function
    is never load-bearing for path safety. It exists so the *stored*
    metadata cannot carry a traversal sequence, a control character, or a
    right-to-left override that makes "invoice.xlsx.exe" render backwards.
    """

    if not raw or not raw.strip():
        raise ValidationException("A filename is required.")

    # Unicode normalisation first: without it "á" and "á" are
    # different strings that render identically, and the charset check
    # below can be walked around with decomposed forms.
    name = unicodedata.normalize("NFKC", raw).strip()

    # Take the basename under *both* separator conventions. The upload
    # arrives from a browser but is consumed on Windows, so "a/b\\c.xlsx"
    # must not survive as a path in either dialect.
    name = name.replace("\\", "/").split("/")[-1]

    # Reject, rather than strip, anything unprintable — NUL, the bidi
    # overrides, embedded newlines. Stripping would silently turn
    # "report\x00.xlsx" into a valid "report.xlsx", which hides a
    # deliberate attack instead of refusing it. A filename containing a
    # control character is never an honest mistake.
    if any(not ch.isprintable() for ch in name):
        raise ValidationException("The filename is not valid.")

    if name in {"", ".", ".."} or name.startswith("."):
        raise ValidationException("The filename is not valid.")

    if len(name) > MAX_FILENAME_LENGTH:
        raise ValidationException(
            f"The filename must be {MAX_FILENAME_LENGTH} characters or fewer."
        )

    if not _SAFE_FILENAME.match(name):
        raise ValidationException(
            "The filename may only contain letters, numbers, spaces and "
            ". _ & ( ) - characters."
        )

    # Exactly one extension, and it must be an allowed one. This rejects
    # the double-extension trick ("report.xlsx.exe") because the *last*
    # extension is what Windows honours.
    extension = name[name.rfind(".") :].lower() if "." in name else ""

    if extension not in ALLOWED_WORKBOOK_EXTENSIONS:
        raise ValidationException(
            "The workbook must be an .xlsx, .xlsm or .xlsb file."
        )

    return name


def validate_workbook_bytes(data: bytes, *, max_bytes: int) -> None:
    """Check the container, not the claimed type.

    A content-type header and a file extension are both caller-controlled.
    The magic number is the cheapest fact about the bytes themselves that
    distinguishes an OOXML workbook from a renamed executable.
    """

    if not data:
        raise ValidationException("The uploaded workbook is empty.")

    if len(data) > max_bytes:
        raise ValidationException(
            f"The workbook exceeds the {max_bytes // (1024 * 1024)}MB limit."
        )

    if data.startswith(_OLE2_MAGIC):
        raise ValidationException(
            "Legacy .xls workbooks are not supported. Save the workbook as "
            ".xlsx or .xlsm and upload it again."
        )

    if not data.startswith(_ZIP_MAGIC):
        raise ValidationException(
            "The uploaded file is not a valid Excel workbook."
        )


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_report_type(value: str) -> ReportType:
    try:
        report_type = ReportType(value)
    except ValueError:
        raise ValidationException(f"Unknown report type: {value}")

    if report_type not in IMPLEMENTED_REPORT_TYPES:
        # Named explicitly rather than "invalid": the type is a real part
        # of the roadmap and the column accepts it, so the honest error is
        # "not built yet", not "does not exist".
        raise ValidationException(
            f"Report type '{report_type.value}' is reserved for a future "
            "release and cannot be used yet."
        )

    return report_type


def validate_output_formats(values: list[str]) -> list[OutputFormat]:
    if not values:
        raise ValidationException("At least one output format is required.")

    formats: list[OutputFormat] = []

    for value in values:
        try:
            output_format = OutputFormat(value)
        except ValueError:
            raise ValidationException(f"Unknown output format: {value}")

        if output_format not in formats:
            formats.append(output_format)

    return formats
