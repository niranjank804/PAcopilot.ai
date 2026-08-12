"""`pa-worker` command line.

    pa-worker enroll --server <url> --token <enrollment-token>
    pa-worker start [--once]
    pa-worker stop
    pa-worker status
    pa-worker diagnostics
    pa-worker test-report [--execution <id>]

`test-report` is the POC entry point: it claims one job (or waits for a
specific execution), runs it with verbose output, and exits — so an
operator can prove the whole path on a Windows box without running the
worker as a service first.

Nothing here prints a credential. `enroll` writes the credential to the
protected credential file and reports only where it went.
"""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from pa_worker import __version__
from pa_worker.client.control_plane import ControlPlaneClient
from pa_worker.config import (
    DEFAULT_CONFIG_DIR,
    WorkerConfig,
    WorkerCredentials,
    log_file,
    pid_file,
)
from pa_worker.diagnostics import probe_host
from pa_worker.errors import ControlPlaneError, WorkerError
from pa_worker.jobs.poller import JobPoller, execute_job
from pa_worker.logging import configure, get_logger

logger = get_logger("cli")


def _config_dir(args: argparse.Namespace) -> Path:
    return Path(args.config_dir) if args.config_dir else DEFAULT_CONFIG_DIR


def _load(args: argparse.Namespace) -> tuple[WorkerConfig, WorkerCredentials | None]:
    directory = _config_dir(args)
    config = WorkerConfig.load(directory)

    if getattr(args, "server", None):
        config.server_url = args.server

    credentials = WorkerCredentials.load(directory)

    return config, credentials


def _client(args: argparse.Namespace) -> ControlPlaneClient:
    config, credentials = _load(args)

    if credentials is None:
        print(
            "This worker is not enrolled. Run:\n"
            "  pa-worker enroll --server <url> --token <enrollment-token>",
            file=sys.stderr,
        )

        raise SystemExit(2)

    return ControlPlaneClient(config, credentials)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def cmd_enroll(args: argparse.Namespace) -> int:
    directory = _config_dir(args)
    config = WorkerConfig.load(directory)
    config.server_url = args.server

    if args.insecure:
        # Only for a local development server with a self-signed cert.
        config.verify_tls = False

    config.save(directory)

    print("Probing this host before enrolling...")

    report = probe_host(deep=not args.skip_probe)

    for name, value in report.checks.items():
        print(f"  {name:12} {value}")

    if not report.capabilities:
        print(
            "\nNo capabilities could be verified on this host. The worker "
            "will enroll but will not be given any jobs until "
            "`pa-worker diagnostics` succeeds.",
            file=sys.stderr,
        )

    client = ControlPlaneClient(config)

    try:
        credentials = client.enroll(args.token, report.to_host_facts())
    except ControlPlaneError as exc:
        print(f"\nEnrollment failed: {exc}", file=sys.stderr)

        return 1

    path = credentials.save(directory)

    print(f"\nEnrolled successfully as worker {credentials.worker_id}")
    print(f"Credential stored at: {path}")
    print(f"Capabilities reported: {', '.join(report.capabilities) or 'none'}")
    print("\nStart the worker with:  pa-worker start")

    return 0


def cmd_diagnostics(args: argparse.Namespace) -> int:
    report = probe_host(deep=not args.quick)

    if args.json:
        print(json.dumps({"checks": report.checks, **report.to_host_facts()}, indent=2))

        return 0

    print(f"PA-Copilot worker {__version__}")
    print(f"Host: {report.hostname} ({report.os})")
    print()
    print("Checks:")

    for name, value in report.checks.items():
        print(f"  {name:12} {value}")

    print()
    print(f"Excel version: {report.excel_version or 'not detected'}")
    print(f"PAfE version:  {report.pafe_version or 'not detected'}")
    print(f"Capabilities:  {', '.join(report.capabilities) or 'none'}")

    required = {"excel", "pafe_automation"}

    if not required.issubset(set(report.capabilities)):
        print(
            "\nThis host cannot run PAfE report jobs yet. Both Excel and the "
            "PAfE automation object must be detected.",
            file=sys.stderr,
        )

        return 1

    return 0


def cmd_diagnostics_pafe(args: argparse.Namespace) -> int:
    """Deep PAfE probe with an explicit four-state verdict.

    Separate from `diagnostics` because it answers a different question:
    not "can this host run jobs" but "exactly where does the PAfE chain
    break". Exit code is non-zero unless automation is actually
    available, so it can gate a deployment script.
    """

    from pa_worker.pafe.probe import PAfEStatus, probe_pafe

    result = probe_pafe()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))

        return 0 if result.status == PAfEStatus.INSTALLED_AND_AUTOMATION_AVAILABLE else 1

    def flag(value: bool | None) -> str:
        if value is None:
            return "UNKNOWN"

        return "YES" if value else "NO"

    print("PA-Copilot worker — PAfE diagnostics")
    print()
    print(f"  Windows version                      {result.windows_version}")
    print(f"  Python version                       {result.python_version}")
    print(f"  Excel version                        {result.excel_version or 'not detected'}")
    print()
    print(f"  PAfE detected                        {flag(result.registry_progid_found)}")
    print(f"  PAfE version                         {result.pafe_version or 'not discoverable'}")
    print(f"  Install directory                    {result.install_directory or 'not found'}")
    print()
    print("  COM chain (IBM's documented access path):")
    print(f"    CognosOffice12.Connect add-in      {flag(result.com_addin_registered)}")
    print(f"    Add-in connected                   {flag(result.com_addin_connected)}")
    print(f"    AutomationServer                   {flag(result.automation_server_available)}")
    print(f"    Application(\"COR\", \"1.1\")          {flag(result.application_object_available)}")
    print(f"    TraceLog accessible                {flag(result.trace_log_accessible)}")
    print()
    print(f"  VERDICT: {result.status.value}")

    if result.notes:
        print()
        print("  Notes:")

        for note in result.notes:
            print(f"    - {note}")

    print()

    if result.status == PAfEStatus.INSTALLED_AND_AUTOMATION_AVAILABLE:
        print("  This host can run PAfE report jobs.")

        return 0

    if result.status == PAfEStatus.NOT_INSTALLED:
        print(
            "  Planning Analytics for Microsoft Excel is not installed.\n"
            "  Install the PAfE client on this host, then re-run this command."
        )
    elif result.status == PAfEStatus.INSTALLED_BUT_UNAVAILABLE:
        print(
            "  PAfE is present but its automation object could not be\n"
            "  reached. Check that the add-in is enabled in Excel\n"
            "  (File > Options > Add-ins > COM Add-ins) and that Excel and\n"
            "  PAfE have the same bitness."
        )
    else:
        print(
            "  PAfE status could not be determined. Excel may have failed to\n"
            "  start, or this host is not Windows."
        )

    return 1


def cmd_start(args: argparse.Namespace) -> int:
    directory = _config_dir(args)
    config, credentials = _load(args)

    configure(level=config.log_level, log_file=str(log_file(directory)))

    if credentials is None:
        print("This worker is not enrolled. Run `pa-worker enroll` first.", file=sys.stderr)

        return 2

    pid_path = pid_file(directory)

    existing = _read_pid(pid_path)

    if existing and _pid_alive(existing):
        print(f"A worker is already running (pid {existing}).", file=sys.stderr)

        return 1

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    client = ControlPlaneClient(config, credentials)

    poller = JobPoller(
        client,
        config,
        # Re-probed at each heartbeat so a host that loses PAfE (add-in
        # disabled, Office update) stops being given jobs without anyone
        # having to notice manually.
        host_facts_provider=lambda: probe_host(deep=False).to_host_facts(),
    )

    def handle_signal(signum, frame):  # noqa: ARG001
        logger.info(f"Received signal {signum}; shutting down after this job")
        poller.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        poller.run_forever(max_iterations=1 if args.once else None)
    finally:
        if pid_path.exists():
            pid_path.unlink()

    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    pid_path = pid_file(_config_dir(args))
    pid = _read_pid(pid_path)

    if not pid or not _pid_alive(pid):
        print("No worker is running.")

        if pid_path.exists():
            pid_path.unlink()

        return 0

    print(f"Stopping worker (pid {pid})...")

    try:
        # SIGTERM/CTRL_BREAK asks the poller to finish the job it is on
        # rather than abandoning a running Excel session mid-refresh.
        if os.name == "nt":
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Could not signal the worker: {type(exc).__name__}", file=sys.stderr)

        return 1

    for _ in range(30):
        if not _pid_alive(pid):
            print("Worker stopped.")

            return 0

        time.sleep(1)

    print(
        "The worker did not stop within 30s. It may be finishing a report; "
        "check the log.",
        file=sys.stderr,
    )

    return 1


def cmd_status(args: argparse.Namespace) -> int:
    directory = _config_dir(args)
    config, credentials = _load(args)

    pid = _read_pid(pid_file(directory))
    running = bool(pid and _pid_alive(pid))

    print(f"PA-Copilot worker {__version__}")
    print(f"Config dir:  {directory}")
    print(f"Server:      {config.server_url}")
    print(f"Enrolled:    {'yes' if credentials else 'no'}")

    if credentials:
        print(f"Worker id:   {credentials.worker_id}")

    print(f"Process:     {'running (pid ' + str(pid) + ')' if running else 'stopped'}")

    if not credentials:
        return 0

    try:
        client = ControlPlaneClient(config, credentials)
        response = client.heartbeat(busy=False)

        print(f"Server says: {response.get('status')}")

        active = response.get("active_execution_ids") or []

        if active:
            print(f"Active jobs: {len(active)}")
    except ControlPlaneError as exc:
        print(f"Server:      unreachable ({exc})")

        return 1

    return 0


def cmd_test_report(args: argparse.Namespace) -> int:
    """POC mode: claim and run exactly one job, verbosely."""

    directory = _config_dir(args)
    config, _ = _load(args)
    config.log_level = "DEBUG"

    configure(level="DEBUG", log_file=str(log_file(directory)))

    client = _client(args)

    print("Reporting host facts and asking for a job...")

    report = probe_host(deep=False)

    client.heartbeat(busy=False, host_facts=report.to_host_facts())

    deadline = time.monotonic() + args.wait

    job = None

    while time.monotonic() < deadline:
        job = client.claim_job()

        if job is not None:
            break

        print("  no job queued yet, waiting...")

        time.sleep(3)

    if job is None:
        print(
            f"\nNo job was claimed within {args.wait}s. Create one with "
            "'Run now' in PA-Copilot, then try again.",
            file=sys.stderr,
        )

        return 1

    if args.execution and str(job["execution_id"]) != args.execution:
        print(
            f"\nClaimed execution {job['execution_id']}, which is not the "
            f"requested {args.execution}. Refusing to run it.",
            file=sys.stderr,
        )

        # Hand it back rather than running someone else's job.
        client.fail_job(job["execution_id"], error_code="cancelled")

        return 1

    print(f"\nClaimed execution {job['execution_id']}")
    print(f"  operation:      {job['operation']}")
    print(f"  output formats: {', '.join(job['output_formats'])}")
    print(f"  workbook:       {job['workbook']['filename']}")
    print(f"  checksum:       {job['workbook']['checksum'][:16]}...")
    print(f"  timeout:        {job['timeout_seconds']}s")
    print()

    try:
        ok = execute_job(client, job, config)
    except WorkerError as exc:
        print(f"\nFAILED: {exc.code.value} — {exc.message}", file=sys.stderr)

        return 1

    if ok:
        print("\nSUCCEEDED — artifacts uploaded and execution reported.")

        return 0

    print("\nFAILED — see the log above and the execution in PA-Copilot.", file=sys.stderr)

    return 1


# ----------------------------------------------------------------------
# Wiring
# ----------------------------------------------------------------------


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass

    try:
        os.kill(pid, 0)

        return True
    except OSError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pa-worker",
        description=(
            "PA-Copilot Report Automation worker (DEVELOPER PREVIEW). Runs "
            "PAfE workbook refreshes on Windows under PA-Copilot's control."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config-dir",
        help="Override the configuration directory.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll = subparsers.add_parser("enroll", help="Enroll this machine.")
    enroll.add_argument("--server", required=True, help="PA-Copilot base URL.")
    enroll.add_argument(
        "--token", required=True, help="Single-use enrollment token."
    )
    enroll.add_argument(
        "--skip-probe",
        action="store_true",
        help="Skip the Excel/PAfE probe (enrolls with no capabilities).",
    )
    enroll.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification. Local development only.",
    )
    enroll.set_defaults(func=cmd_enroll)

    start = subparsers.add_parser("start", help="Start polling for jobs.")
    start.add_argument("--server", help="Override the configured server URL.")
    start.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll iteration and exit.",
    )
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help="Stop a running worker.")
    stop.set_defaults(func=cmd_stop)

    status = subparsers.add_parser("status", help="Show worker status.")
    status.add_argument("--server", help="Override the configured server URL.")
    status.set_defaults(func=cmd_status)

    diagnostics = subparsers.add_parser(
        "diagnostics", help="Probe Excel, PAfE and export capabilities."
    )
    diagnostics.add_argument(
        "--quick", action="store_true", help="Skip launching Excel."
    )
    diagnostics.add_argument(
        "--json", action="store_true", help="Machine-readable output."
    )
    diagnostics.set_defaults(func=cmd_diagnostics)

    diagnostics_pafe = subparsers.add_parser(
        "diagnostics-pafe",
        help="Deep PAfE probe: exactly where the COM chain breaks.",
    )
    diagnostics_pafe.add_argument(
        "--json", action="store_true", help="Machine-readable output."
    )
    diagnostics_pafe.set_defaults(func=cmd_diagnostics_pafe)

    test_report = subparsers.add_parser(
        "test-report", help="POC: claim and run exactly one job."
    )
    test_report.add_argument("--server", help="Override the configured server URL.")
    test_report.add_argument(
        "--execution",
        help="Only run this execution id; hand back anything else.",
    )
    test_report.add_argument(
        "--wait",
        type=int,
        default=60,
        help="Seconds to wait for a job to appear (default 60).",
    )
    test_report.set_defaults(func=cmd_test_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    configure(level="INFO")

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)

        return 130
    except SystemExit:
        raise
    except ControlPlaneError as exc:
        print(f"Error: {exc}", file=sys.stderr)

        return 1


if __name__ == "__main__":
    sys.exit(main())
