"""Worker-side security properties: allowlist, paths, redaction, parity."""

import pytest

from pa_worker.errors import WorkerError, WorkerErrorCode
from pa_worker.execution.operations import (
    ALLOWED_OPERATIONS,
    WorkerOperation,
    resolve_operation,
)
from pa_worker.execution.workspace import Workspace
from pa_worker.logging import redact


class TestOperationAllowlist:
    """No payload may describe behaviour — only select from a fixed set."""

    def test_the_implemented_operation_resolves(self):
        assert resolve_operation("REFRESH_WORKBOOK") == (
            WorkerOperation.REFRESH_WORKBOOK
        )

    @pytest.mark.parametrize(
        "payload",
        [
            "EXECUTE_SCRIPT",
            "RUN_VBA",
            "Application.Run('EvilMacro')",
            "Shell('cmd.exe /c whoami')",
            "__import__('os').system('calc')",
            "REFRESH_WORKBOOK; DROP TABLE users",
            "refresh_workbook",  # case matters
            "",
            "../../etc/passwd",
        ],
    )
    def test_anything_not_on_the_list_is_refused(self, payload):
        with pytest.raises(WorkerError) as exc_info:
            resolve_operation(payload)

        assert exc_info.value.code == WorkerErrorCode.INTERNAL_ERROR

    def test_reserved_operations_have_no_handler(self):
        # Named for vocabulary parity with the control plane, but asking
        # for one today must fail loudly rather than silently no-op.
        for operation in (
            WorkerOperation.REFRESH_SHEET,
            WorkerOperation.EXPORT_XLSX,
            WorkerOperation.EXPORT_PDF,
        ):
            assert operation not in ALLOWED_OPERATIONS

            with pytest.raises(WorkerError):
                resolve_operation(operation.value)

    def test_resolution_is_a_lookup_not_a_getattr(self):
        # Guards against a refactor to getattr()/eval(), which would turn
        # the operation name into an arbitrary attribute selector.
        import inspect

        from pa_worker.execution import operations

        source = inspect.getsource(operations)

        for forbidden in ("eval(", "exec(", "getattr(", "__import__", "importlib"):
            assert forbidden not in source, forbidden


class TestWorkspacePathSafety:

    def test_the_supplied_filename_never_becomes_the_path(self, tmp_path):
        with Workspace("exec-1", root=tmp_path) as workspace:
            path = workspace.write_workbook(
                b"PK\x03\x04" + b"\x00" * 32, "Monthly P&L.xlsx"
            )

            # Named after a generated UUID, not after anything supplied.
            assert path.parent == workspace.path
            assert "Monthly" not in path.name
            assert path.name.startswith("workbook-")

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../windows/system32/evil.xlsx",
            "..\\..\\..\\evil.xlsm",
            "C:\\Windows\\System32\\evil.xlsx",
            "/etc/passwd",
            "....//....//evil.xlsx",
            "evil.xlsx\x00.exe",
        ],
    )
    def test_traversal_cannot_escape_the_workspace(self, tmp_path, hostile):
        with Workspace("exec-1", root=tmp_path) as workspace:
            path = workspace.write_workbook(b"PK\x03\x04" + b"\x00" * 32, hostile)

            # Structural, not defensive: the hostile string only ever
            # contributes a suffix, and only from an allowlist.
            assert workspace.path in path.parents
            assert path.suffix in {".xlsx", ".xlsm", ".xlsb"}
            assert path.resolve().is_relative_to(workspace.path.resolve())

    def test_a_disallowed_suffix_falls_back_to_xlsx(self, tmp_path):
        with Workspace("exec-1", root=tmp_path) as workspace:
            path = workspace.write_workbook(b"PK\x03\x04" + b"\x00" * 32, "evil.exe")

            assert path.suffix == ".xlsx"

    def test_non_workbook_content_is_refused(self, tmp_path):
        with Workspace("exec-1", root=tmp_path) as workspace:
            with pytest.raises(WorkerError) as exc_info:
                workspace.write_workbook(b"MZ\x90\x00", "report.xlsx")

            assert exc_info.value.code == WorkerErrorCode.WORKBOOK_INVALID

    def test_unknown_artifact_format_is_refused(self, tmp_path):
        with Workspace("exec-1", root=tmp_path) as workspace:
            with pytest.raises(WorkerError):
                workspace.artifact_path("exe")

    def test_the_workspace_is_removed_on_exit(self, tmp_path):
        with Workspace("exec-1", root=tmp_path) as workspace:
            path = workspace.path
            workspace.write_workbook(b"PK\x03\x04" + b"\x00" * 32, "r.xlsx")

        assert not path.exists()


class TestLogRedaction:

    @pytest.mark.parametrize(
        "secret",
        [
            "pacw-secret-abc123XYZ_-def456",
            "pacw-enroll-abc123XYZ_-def456",
        ],
    )
    def test_worker_credentials_are_redacted(self, secret):
        assert secret not in redact(f"authenticating with {secret}")

    def test_bearer_tokens_are_redacted(self):
        message = (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123"
        )

        result = redact(message)

        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    @pytest.mark.parametrize(
        "message",
        [
            "password=hunter2",
            "password: hunter2",
            'api_key="sk-abc123"',
            "TM1 secret=topsecret",
            "token: abcdef123456",
        ],
    )
    def test_labelled_secrets_are_redacted(self, message):
        result = redact(message)

        assert "hunter2" not in result
        assert "sk-abc123" not in result
        assert "topsecret" not in result
        assert "abcdef123456" not in result

    def test_redaction_recurses_through_diagnostics(self):
        payload = {
            "step": "logon",
            "nested": {"password": "hunter2"},
            "list": ["pacw-secret-abcdefghijklmnop"],
        }

        result = redact(payload)

        assert "hunter2" not in str(result)
        assert "pacw-secret-abcdefghijklmnop" not in str(result)

    def test_ordinary_text_is_untouched(self):
        message = "Refreshed 12 reports in 34s"

        assert redact(message) == message


class TestErrorCodeParity:
    """The worker and the control plane must agree on the vocabulary."""

    def test_every_worker_code_exists_on_the_control_plane(self):
        # Read from the backend source rather than importing it — the
        # worker deliberately has no dependency on the backend package.
        import re
        from pathlib import Path

        backend_errors = (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "src"
            / "reports"
            / "errors.py"
        )

        if not backend_errors.exists():
            pytest.skip("backend source not available")

        text = backend_errors.read_text(encoding="utf-8")
        # Names contain digits (TM1_AUTH_FAILED), values contain digits
        # (tm1_auth_failed) — both character classes must allow them.
        server_codes = set(
            re.findall(r'^\s+[A-Z0-9_]+ = "([a-z0-9_]+)"', text, re.M)
        )

        for code in WorkerErrorCode:
            assert code.value in server_codes, (
                f"{code.value} is unknown to the control plane and would be "
                "coerced to internal_error, losing the diagnosis"
            )
