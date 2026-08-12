import pytest

from src.core.exceptions import ValidationException
from src.reports.validation import (
    checksum,
    sanitize_filename,
    validate_output_formats,
    validate_report_type,
    validate_workbook_bytes,
)

ZIP_HEADER = b"PK\x03\x04"
OLE2_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _workbook(size: int = 100) -> bytes:
    return ZIP_HEADER + b"\x00" * size


class TestFilenameSanitization:

    @pytest.mark.parametrize(
        "name",
        [
            "Monthly P&L.xlsx",
            "budget_2026.xlsm",
            "Report (final).xlsb",
            "a.xlsx",
        ],
    )
    def test_accepts_realistic_workbook_names(self, name):
        assert sanitize_filename(name) == name

    @pytest.mark.parametrize(
        "attack",
        [
            "../../../windows/system32/evil.xlsx",
            "..\\..\\..\\Users\\Public\\evil.xlsx",
            "/etc/passwd.xlsx",
            "C:\\Windows\\System32\\config.xlsx",
            "subdir/report.xlsx",
            "subdir\\report.xlsx",
        ],
    )
    def test_strips_every_path_component(self, attack):
        # Both separator conventions matter: uploads arrive from a
        # browser but are consumed on Windows.
        result = sanitize_filename(attack)

        assert "/" not in result
        assert "\\" not in result
        assert ".." not in result

    @pytest.mark.parametrize(
        "attack",
        [
            "report.xlsx.exe",
            "report.xlsx.bat",
            "report.xlsx.ps1",
            "payload.exe",
            "script.vbs",
            "macro.bas",
        ],
    )
    def test_rejects_executable_extensions(self, attack):
        # Windows honours the *last* extension, so the double-extension
        # trick is what this is really guarding.
        with pytest.raises(ValidationException):
            sanitize_filename(attack)

    def test_rejects_bidi_override_disguise(self):
        # U+202E renders "…fdp.xlsx" as "…xslx.pdf" — a classic way to
        # make an executable look like a document.
        with pytest.raises(ValidationException):
            sanitize_filename("report\u202exslx.exe")

    def test_rejects_control_characters(self):
        with pytest.raises(ValidationException):
            sanitize_filename("report\x00.xlsx")

    def test_rejects_newline_injection(self):
        # Would otherwise be able to forge a Content-Disposition header.
        with pytest.raises(ValidationException):
            sanitize_filename('report".xlsx\r\nX-Injected: 1')

    @pytest.mark.parametrize("name", ["", "   ", ".", "..", ".hidden.xlsx"])
    def test_rejects_degenerate_names(self, name):
        with pytest.raises(ValidationException):
            sanitize_filename(name)

    def test_rejects_overlong_names(self):
        with pytest.raises(ValidationException):
            sanitize_filename("a" * 200 + ".xlsx")

    def test_normalises_unicode_before_checking(self):
        # Decomposed forms must not be a way around the charset rule.
        with pytest.raises(ValidationException):
            sanitize_filename("re\u0301port\u0000.xlsx")


class TestWorkbookBytes:

    def test_accepts_ooxml_container(self):
        validate_workbook_bytes(_workbook(), max_bytes=1024 * 1024)

    def test_rejects_empty_upload(self):
        with pytest.raises(ValidationException):
            validate_workbook_bytes(b"", max_bytes=1024)

    def test_rejects_oversize_upload_with_a_useful_message(self):
        with pytest.raises(ValidationException) as exc_info:
            validate_workbook_bytes(_workbook(5000), max_bytes=1024)

        assert "limit" in str(exc_info.value).lower()

    def test_rejects_legacy_xls_specifically(self):
        # A distinct message, because "save it as .xlsx" is actionable
        # and "not a valid workbook" is not.
        with pytest.raises(ValidationException) as exc_info:
            validate_workbook_bytes(OLE2_HEADER + b"\x00" * 50, max_bytes=1024)

        assert ".xlsx" in str(exc_info.value)

    @pytest.mark.parametrize(
        "payload",
        [
            b"MZ\x90\x00",  # Windows PE executable
            b"#!/bin/sh\necho pwned",
            b"<html><body>not a workbook</body></html>",
            b"\x7fELF",
        ],
    )
    def test_rejects_non_workbook_content_regardless_of_name(self, payload):
        # The magic number is the only caller-independent fact available;
        # extension and content-type are both attacker-controlled.
        with pytest.raises(ValidationException):
            validate_workbook_bytes(payload + b"\x00" * 50, max_bytes=1024)


class TestChecksum:

    def test_is_sha256_hex(self):
        assert checksum(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )

    def test_differs_for_a_single_changed_byte(self):
        assert checksum(b"report-v1") != checksum(b"report-v2")


class TestReportType:

    def test_accepts_the_implemented_type(self):
        assert validate_report_type("pafe_workbook").value == "pafe_workbook"

    def test_reserved_types_say_so_rather_than_pretending_to_be_invalid(self):
        # Honest error: the type is real and on the roadmap, it is just
        # not built. "Invalid" would send someone hunting for a typo.
        with pytest.raises(ValidationException) as exc_info:
            validate_report_type("tm1_native")

        assert "future release" in str(exc_info.value)

    def test_unknown_types_are_rejected(self):
        with pytest.raises(ValidationException):
            validate_report_type("not_a_real_type")


class TestOutputFormats:

    def test_accepts_and_deduplicates(self):
        result = validate_output_formats(["xlsx", "pdf", "xlsx"])

        assert [item.value for item in result] == ["xlsx", "pdf"]

    def test_requires_at_least_one(self):
        with pytest.raises(ValidationException):
            validate_output_formats([])

    def test_rejects_unknown_format(self):
        with pytest.raises(ValidationException):
            validate_output_formats(["xlsx", "docx"])
