"""Fixtures shared by tests/live/*: a real TM1 server, used safely.

Configuration comes only from environment variables set for the run by
scripts/run_live_validation.ps1, which reads the password at a masked
prompt. Nothing here is hardcoded or accepted from chat:

    TM1_ADDRESS, TM1_USER, TM1_PASSWORD   required
    TM1_PORT (8010), TM1_SSL (true)       optional

Three things are separate opt-ins, never implied by each other:

* Reading: the default once the TM1_* variables are set.
* Writing (tests marked `live_write`): TM1_LIVE_WRITE=1, the server's name
  typed exactly (TM1_LIVE_WRITE_SERVER), LIVE_WRITE_SCOPE_CONFIRMED=1, and
  the target listed in the operator's own inventory of approved DEV/test
  servers — a file the operator maintains, never written by a run:
  %USERPROFILE%\\.pa-copilot\\live-targets.json (or LIVE_TARGETS_FILE),
  [{"address": "...", "port": 12354, "server_name": "...", "purpose": "..."}].
  All four must agree with what the server itself reports, or writes are
  BLOCKED.
* Paid AI calls (tests marked `live_ai`): LIVE_AI=1.

With LIVE_EVIDENCE_DIR set, the run writes manifest.json (fixtures planned,
created, cleaned) and results.json (allowlisted fields only) there.
"""

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user

# Bounds for one run. Writes stop being started past the time limit.
MAX_RUN_MINUTES = float(os.environ.get("LIVE_MAX_MINUTES", "15"))
MAX_FIXTURE_OBJECTS = 12
MAX_CELLS_PER_CHANGE = 10
FIXTURE_PREFIX = "zzPACopilotLive"


def pytest_collection_modifyitems(config, items):
    # A module-level pytestmark does not reach every file; mark them all, so
    # `-m live` selects the whole live suite rather than silently dropping
    # the files that lacked the mark.
    for item in items:
        if "tests/live/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.live)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set — skipping live TM1 validation test")
    return value


class LiveRun:
    """One run: its id, its limits, and the record of what it touched."""

    def __init__(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.run_id = f"{stamp}_{random.randint(0, 0xFFFF):04x}"
        self.started = time.monotonic()
        self.manifest = {
            "run_id": self.run_id,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "transport": "DIRECT",
            "target": None,
            "authorization": None,
            "limits": {"max_minutes": MAX_RUN_MINUTES, "max_fixture_objects": MAX_FIXTURE_OBJECTS,
                       "max_cells_per_change": MAX_CELLS_PER_CHANGE},
            "fixtures": [],
        }
        self.results: list[dict] = []

    def name(self, kind: str) -> str:
        # Unique, and short enough for TM1 names.
        return f"{FIXTURE_PREFIX}_{self.run_id}_{kind}"

    def check_time(self) -> None:
        if (time.monotonic() - self.started) / 60 > MAX_RUN_MINUTES:
            pytest.skip("BLOCKED: the run's time limit is spent; no further writes are started")

    def write(self) -> None:
        out = os.environ.get("LIVE_EVIDENCE_DIR")
        if not out:
            return
        folder = Path(out)
        folder.mkdir(parents=True, exist_ok=True)
        self.manifest["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (folder / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        (folder / "results.json").write_text(json.dumps(self.results, indent=2), encoding="utf-8")


_RUN = LiveRun()


@pytest.fixture(scope="session")
def live_run() -> LiveRun:
    return _RUN


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        if "tests/live/" not in report.nodeid.replace("\\", "/"):
            return
        outcome = report.outcome
        reason = None
        if report.skipped:
            text = str(report.longrepr[-1]) if isinstance(report.longrepr, tuple) else ""
            outcome = "BLOCKED" if "BLOCKED" in text else "SKIPPED"
            # Allowlisted: the skip reason is ours, written in this suite.
            reason = text.replace("Skipped: ", "")[:200]
        elif report.failed:
            outcome = "FAILED" if report.when == "call" else "ERROR"
            reason = _error_category(report)
        else:
            outcome = "PASSED"
        _RUN.results.append({
            "test": report.nodeid.split("::")[-1],
            "file": report.nodeid.split("::")[0].split("/")[-1],
            "outcome": outcome,
            "seconds": round(report.duration, 2),
            "reason": reason,
            # record_property values: layer, observed, compatibility path.
            "properties": {k: v for k, v in report.user_properties if k in
                           ("layer", "transport", "observed", "compat_path", "audit")},
        })


# The exception's class only, never its message: messages can carry server
# details. Each class maps to the classification the report uses.
_CATEGORIES = {
    "TM1AuthenticationError": "environment/authentication: TM1 rejected the credentials",
    "TM1NotFoundError": "not found on the server",
    "TM1OutcomeUnknownError": "no answer from TM1 (network, timeout or server error); for a write, outcome unknown",
    "TM1ConnectionError": "TM1 refused or could not be reached",
    "TM1pyRestException": "TM1 REST error",
    "TM1pyNetworkException": "network",
    "ConnectionError": "network",
    "Timeout": "network/timeout",
    "AssertionError": "assertion: product behaviour differed from the expectation",
}


def _error_category(report) -> str:
    crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
    message = str(getattr(crash, "message", "") or "")
    if message.startswith("assert"):
        # A bare assert reports its expression, not the exception class.
        message = "AssertionError: " + message
    name = message.split(":", 1)[0].strip().split(".")[-1].split(" ")[0]
    for key, category in _CATEGORIES.items():
        if name.endswith(key):
            return f"{name}: {category}"
    return f"{name or 'error'}: unclassified"


def pytest_sessionfinish(session, exitstatus):
    _RUN.write()


@pytest.fixture
def live_tm1_config() -> dict:
    return {
        "address": _require_env("TM1_ADDRESS"),
        "port": int(os.environ.get("TM1_PORT", "8010")),
        "ssl": os.environ.get("TM1_SSL", "true").strip().lower() == "true",
        "username": _require_env("TM1_USER"),
        "password": _require_env("TM1_PASSWORD"),
        "namespace": os.environ.get("TM1_NAMESPACE"),
    }


@pytest.fixture
def live_credentials_key():
    # Every test that stores the password in the test database (encrypted,
    # with this throwaway key, rolled back with the test) passes through
    # here; without the operator's consent they are BLOCKED.
    if os.environ.get("LIVE_CREDENTIAL_STORAGE_CONSENT") != "1":
        pytest.skip("BLOCKED: no consent to store the password in the test database")
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
async def live_connection(db_session, live_credentials_key, live_tm1_config):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Live Validation",
        address=live_tm1_config["address"],
        port=live_tm1_config["port"],
        ssl=live_tm1_config["ssl"],
        username=live_tm1_config["username"],
        password=live_tm1_config["password"],
    )

    return org, user, connection


@pytest.fixture
def direct_tm1(live_tm1_config):
    """A TM1 session made directly with TM1py: provisions run-owned fixtures
    and verifies results independently of PA-Copilot's own code."""

    from TM1py import TM1Service

    cfg = live_tm1_config
    tm1 = TM1Service(address=cfg["address"], port=cfg["port"], ssl=cfg["ssl"],
                     user=cfg["username"], password=cfg["password"], timeout=60)
    try:
        yield tm1
    finally:
        try:
            tm1.logout()
        except Exception:  # noqa: BLE001 - the session ends either way
            pass


def authorize_write(env: dict, reported: str, cfg: dict, inventory: list | None) -> tuple[bool, str]:
    """Whether this run may write to this target. Pure, so each refusal is
    unit-tested without a server. Every condition must hold; the first
    that does not is the reason writes are BLOCKED."""

    if env.get("TM1_LIVE_WRITE") != "1":
        return False, "TM1_LIVE_WRITE=1 not set — write validation not authorized"
    typed = env.get("TM1_LIVE_WRITE_SERVER")
    if not typed:
        return False, "the server's name was not typed — write validation not authorized"
    if env.get("LIVE_WRITE_SCOPE_CONFIRMED") != "1":
        return False, "the write scope was not confirmed"
    if reported != typed:
        return False, "the typed name does not match the name the server reports"
    if inventory is None:
        return False, "no operator inventory of approved DEV/test servers"
    approved = [
        e for e in inventory
        if isinstance(e, dict)
        and str(e.get("address", "")).lower() == str(cfg["address"]).lower()
        and str(e.get("port", "")) == str(cfg["port"])
        and e.get("server_name") == reported
    ]
    if not approved:
        return False, "this address, port and server are not in the operator's approved inventory"
    return True, str(approved[0].get("purpose", ""))[:80]


def _load_inventory() -> list | None:
    path = Path(os.environ.get("LIVE_TARGETS_FILE")
                or Path.home() / ".pa-copilot" / "live-targets.json")
    if not path.exists():
        return None
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return entries if isinstance(entries, list) else None


@pytest.fixture
def write_target(request, live_tm1_config, live_run):
    """Writes are allowed only for this target, in this run, within scope,
    or the test is BLOCKED (skipped, reason recorded) before anything is
    written. Identity is read first with two bounded calls: the server's
    name and version — nothing about its business data."""

    # Everything that can be checked without the server is checked first, so
    # an unauthorized run never contacts the target at all.
    if os.environ.get("TM1_LIVE_WRITE") != "1":
        pytest.skip("BLOCKED: TM1_LIVE_WRITE=1 not set — write validation not authorized")
    inventory = _load_inventory()
    ok, detail = authorize_write(dict(os.environ), os.environ.get("TM1_LIVE_WRITE_SERVER", ""),
                                 live_tm1_config, inventory)
    if not ok:
        pytest.skip(f"BLOCKED: {detail}")
    direct_tm1 = request.getfixturevalue("direct_tm1")
    reported = direct_tm1.server.get_server_name()
    version = direct_tm1.server.get_product_version()
    ok, detail = authorize_write(dict(os.environ), reported, live_tm1_config, inventory)
    if not ok:
        pytest.skip(f"BLOCKED: {detail}")

    cfg = live_tm1_config
    target = {"server_name": reported, "version": version, "port": cfg["port"],
              "address_kind": "loopback" if cfg["address"].lower() in ("localhost", "127.0.0.1") else "other"}
    if live_run.manifest["target"] not in (None, target):
        pytest.skip("BLOCKED: the target changed during the run")
    live_run.manifest["target"] = target
    live_run.manifest["authorization"] = {
        "basis": "operator inventory entry + typed server name + scope confirmation",
        "inventory_purpose": detail,
        "permitted": ["create/update/delete run-owned processes, dimensions, cube",
                      "write cells and rules of the run-owned cube", "run run-owned processes"],
    }
    live_run.check_time()
    return target


class OwnedFixtures:
    """Objects this run created, and only those: absence is checked before
    creating, a name that already exists is refused rather than adopted,
    and cleanup deletes only what was confirmed created here."""

    def __init__(self, tm1, run: LiveRun):
        self.tm1, self.run, self.created = tm1, run, []

    def _entry(self, kind, name):
        entry = {"kind": kind, "name": name, "status": "planned"}
        self.run.manifest["fixtures"].append(entry)
        if sum(1 for f in self.run.manifest["fixtures"] if f["status"] != "planned") >= MAX_FIXTURE_OBJECTS:
            pytest.skip("BLOCKED: the run's fixture limit is reached")
        return entry

    def _exists(self, kind, name) -> bool:
        return {"process": self.tm1.processes.exists, "dimension": self.tm1.dimensions.exists,
                "cube": self.tm1.cubes.exists}[kind](name)

    def create(self, kind, name, make):
        entry = self._entry(kind, name)
        if self._exists(kind, name):
            entry["status"] = "refused: name already exists"
            pytest.fail(f"refusing to adopt an existing {kind}: {name}")
        try:
            make()
        except Exception:
            entry["status"] = "ambiguous" if self._exists(kind, name) else "not created"
            raise
        entry["status"] = "created"
        self.created.append(entry)

    def confirm_created_by_product(self, kind, name):
        """Record an object PA-Copilot itself created in this run, once its
        creation was confirmed (absent before, present now)."""

        entry = self._entry(kind, name)
        entry["status"] = "created (by PA-Copilot)"
        self.created.append(entry)

    def cleanup(self):
        order = {"process": 0, "cube": 1, "dimension": 2}
        for entry in sorted(self.created, key=lambda e: order[e["kind"]]):
            try:
                if self._exists(entry["kind"], entry["name"]):
                    {"process": self.tm1.processes.delete, "dimension": self.tm1.dimensions.delete,
                     "cube": self.tm1.cubes.delete}[entry["kind"]](entry["name"])
                entry["status"] = "cleaned" if not self._exists(entry["kind"], entry["name"]) else "REMAINS"
            except Exception as exc:  # noqa: BLE001 - recorded; the rest still cleaned
                entry["status"] = f"cleanup failed ({type(exc).__name__})"


@pytest.fixture
def owned(write_target, direct_tm1, live_run):
    fixtures = OwnedFixtures(direct_tm1, live_run)
    try:
        yield fixtures
    finally:
        fixtures.cleanup()
