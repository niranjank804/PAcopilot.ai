"""Worker configuration and the on-disk credential store.

Configuration and credentials are kept in two separate files for one
reason: the config file is the one an administrator edits, pastes into a
ticket, or checks into a configuration-management repo, and the
credential file is the one that must never go anywhere. Keeping the
credential out of the editable file makes that separation the default
rather than a discipline.

On Windows the credential file is written with an ACL granting access to
the owning account and Administrators only. That is best-effort — if the
ACL cannot be applied the worker logs a warning rather than refusing to
run, because an unusable worker is not a security improvement. The
control plane's short token lifetime and rotation support are the real
mitigations.
"""

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pa_worker.logging import get_logger

logger = get_logger("config")

DEFAULT_CONFIG_DIR = Path(
    os.environ.get("PA_WORKER_HOME")
    or (Path(os.environ.get("PROGRAMDATA", Path.home())) / "PA-Copilot" / "worker")
)

CONFIG_FILENAME = "worker.json"
CREDENTIAL_FILENAME = "credentials.json"
PID_FILENAME = "worker.pid"
LOG_FILENAME = "worker.log"


@dataclass
class WorkerConfig:
    """Everything non-secret about how this worker behaves."""

    server_url: str = "http://localhost:8000"

    # How often to ask for work when idle, and to extend the lease while
    # running. Kept at or below the server's heartbeat expectation; the
    # server echoes its own interval on every heartbeat and the poller
    # adopts it, so this is only the value used before the first
    # successful heartbeat.
    poll_interval_seconds: float = 10.0
    heartbeat_interval_seconds: float = 30.0

    # Hard ceiling the *parent* process enforces by killing the child.
    # The server also sends a per-execution timeout; the effective limit
    # is the smaller of the two, so neither side can be talked past the
    # other's bound.
    max_execution_seconds: int = 1800

    # How long Excel is given to become responsive to COM after launch.
    excel_startup_timeout_seconds: int = 120

    # Retain the isolated working directory after a failure, for support.
    # Off by default: those directories contain customer report data.
    keep_workspace_on_failure: bool = False

    verify_tls: bool = True
    log_level: str = "INFO"

    # Optional local TM1 credentials for PAfE Logon, keyed by connection
    # id. Deliberately NOT sent by the control plane — see
    # docs/report-automation/README.md, "Authentication scenarios".
    # Values live in the credential file, never here.
    tm1_logon_enabled: bool = False

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "WorkerConfig":
        path = (config_dir or DEFAULT_CONFIG_DIR) / CONFIG_FILENAME

        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))

        known = {key: data[key] for key in data if key in cls.__dataclass_fields__}

        return cls(**known)

    def save(self, config_dir: Path | None = None) -> Path:
        directory = config_dir or DEFAULT_CONFIG_DIR
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / CONFIG_FILENAME
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

        return path


@dataclass
class WorkerCredentials:
    """The long-lived machine credential, plus who it belongs to."""

    worker_id: str
    worker_secret: str
    organization_id: str
    secret_version: int = 1

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "WorkerCredentials | None":
        path = (config_dir or DEFAULT_CONFIG_DIR) / CREDENTIAL_FILENAME

        if not path.exists():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))

        return cls(
            worker_id=data["worker_id"],
            worker_secret=data["worker_secret"],
            organization_id=data["organization_id"],
            secret_version=int(data.get("secret_version", 1)),
        )

    def save(self, config_dir: Path | None = None) -> Path:
        directory = config_dir or DEFAULT_CONFIG_DIR
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / CREDENTIAL_FILENAME

        # Create with restrictive permissions *before* writing, so the
        # secret is never briefly present in a world-readable file.
        path.touch(mode=0o600, exist_ok=True)

        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

        _restrict_windows_acl(path)

        return path

    @staticmethod
    def delete(config_dir: Path | None = None) -> None:
        path = (config_dir or DEFAULT_CONFIG_DIR) / CREDENTIAL_FILENAME

        if path.exists():
            path.unlink()


def _restrict_windows_acl(path: Path) -> None:
    """Owner + Administrators + SYSTEM only, inheritance disabled.

    `os.chmod` is close to a no-op for access control on Windows, so the
    POSIX mode above does not actually protect this file there. icacls is
    the supported way to do it without adding a pywin32 dependency to
    this module (which must import on Linux for the test suite).
    """

    if os.name != "nt":
        return

    account = os.environ.get("USERNAME")

    if not account:
        return

    try:
        subprocess.run(
            [
                "icacls",
                str(path),
                # Drop inherited ACEs rather than merging with them —
                # otherwise a permissive parent directory ACL survives.
                "/inheritance:r",
                "/grant:r",
                f"{account}:F",
                "/grant:r",
                "*S-1-5-32-544:F",  # BUILTIN\Administrators, locale-independent
                "/grant:r",
                "*S-1-5-18:F",  # NT AUTHORITY\SYSTEM
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        # Not fatal: refusing to run would trade a hardening measure for
        # an outage. Loud enough to be noticed and fixed.
        logger.warning(
            "Could not restrict permissions on the credential file "
            f"({type(exc).__name__}). Verify its ACL manually."
        )


def pid_file(config_dir: Path | None = None) -> Path:
    return (config_dir or DEFAULT_CONFIG_DIR) / PID_FILENAME


def log_file(config_dir: Path | None = None) -> Path:
    return (config_dir or DEFAULT_CONFIG_DIR) / LOG_FILENAME
