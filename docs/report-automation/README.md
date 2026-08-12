# PA-Copilot Report Automation

> ## ⚠️ DEVELOPER PREVIEW / POC
>
> This feature has **not** been tested against a real IBM Planning
> Analytics for Microsoft Excel installation. The Excel automation,
> control plane, security model and failure handling are implemented and
> tested; the IBM PAfE API calls themselves are **NOT VERIFIED** on a
> live PAfE host. See [Verification status](#verification-status).
>
> Do not deploy this to production.

*Automate the Planning Analytics reports your teams already run manually.*

---

## 1. Architecture

Microsoft Excel and PAfE only run on Windows, take minutes per report,
and hold a desktop session. None of that can happen inside the Render web
process. So the feature splits into a **control plane** (PA-Copilot) and a
**worker** (the customer's Windows machine):

```
              PA-COPILOT CLOUD                    CUSTOMER WINDOWS HOST
        ┌──────────────────────────┐            ┌────────────────────────┐
        │ FastAPI control plane    │            │ pa-worker              │
        │  · report definitions    │  outbound  │  · Excel via COM       │
        │  · workbook custody      │◄───HTTPS───│  · IBM PAfE automation │
        │  · execution queue       │   (only)   │  · isolated workspace  │
        │  · artifacts + audit     │            │  · subprocess timeout  │
        │ PostgreSQL               │            └───────────┬────────────┘
        └──────────────────────────┘                        │
                                                            ▼
                                                    TM1 / PAW server
```

**The worker dials out.** It opens no listening port and needs no inbound
firewall rule. PA-Copilot never connects to the customer's network.

### Key design decisions

| Decision | Why |
|---|---|
| Worker is a separate process, not a thread in the API | Excel needs Windows, a desktop session, and minutes per job |
| Excel runs in a **child process** of the worker | IBM's `Wait()` blocks uninterruptibly; the only way to bound it is to kill the process from outside |
| `FOR UPDATE SKIP LOCKED` claim | Two workers polling simultaneously take different rows — never the same job twice |
| Execution rows are immutable; retries are new rows | A terminal execution can never re-enter RUNNING, so anything already delivered cannot be delivered twice |
| Lease + heartbeat | A worker that loses power stops owning its job; the reaper reclaims it |
| Allowlisted operation verbs | There is no field in the job payload that can carry code |

---

## 2. Prerequisites

### Control plane
- PA-Copilot backend at `a7d31f905c48` or later (`alembic upgrade head`)
- Permissions seeded (`python scripts/seed_permissions.py`)

### Windows worker host
| Requirement | Notes |
|---|---|
| Windows 10/11 or Windows Server 2019+ | COM automation is Windows-only |
| Microsoft Excel (desktop) | Excel 2016 / Microsoft 365 desktop. **Not** Excel Online or Office Web |
| IBM Planning Analytics for Microsoft Excel (PAfE/PAx) | Must be installed and the COM add-in `CognosOffice12.Connect` registered |
| Python 3.11+ | |
| An interactive desktop session | Excel COM automation in Session 0 (a plain Windows service) is unsupported by Microsoft and not attempted here — see [Known limitations](#12-known-pa-copilot-limitations) |
| A printer driver | Only if PDF output is needed; Excel cannot render PDF without one |

```powershell
cd worker
pip install -r requirements.txt -r requirements-windows.txt
pip install -e .
```

---

## 3. IBM API configuration

PA-Copilot calls the IBM automation object directly over COM:

```
Application.COMAddIns("CognosOffice12.Connect")
    .Object.AutomationServer.Application("COR", "1.1")
```

**No VBA is imported or executed.** IBM's `CognosOfficeAutomationExample.bas`
and `CognosOfficeMessageSuppressor.cls` exist so a human writing VBA gets a
convenience wrapper; calling the COM object from Python reaches the same
documented API without running any macro code. That is what makes the
"no arbitrary VBA execution" boundary real rather than aspirational.

### IBM APIs this worker uses

Verified against IBM's own documentation source
([globalapi.md](https://github.com/IBM/paxapi/blob/master/source/includes/globalapi.md)):

| API | Use |
|---|---|
| `RefreshAllData()` | Refresh every report in the workbook |
| `Wait()` | **Completion mechanism** — "Holds VBA thread until background tasks complete" |
| `TraceLog()` | Capture IBM's automation log; also used to detect silent failures |
| `TraceError(msg)` | Annotate IBM's log |
| `SuppressMessages(bool)` | Prevent modal dialogs blocking an unattended run |
| `Logon(url, user, password, namespace)` | Optional, see below |
| `Logoff()` | Session teardown |
| `UserAgentSCReleaseFull` / `UserAgent` | PAfE version detection |

**There is no `sleep()` anywhere in the refresh path.** `Wait()` is the
documented mechanism and is what the worker calls; a test asserts no
`time.sleep` exists in the PAfE or runner modules.

### Why `RefreshAllData()` returning cleanly is not enough

PAfE reports connection and authentication problems into its **trace
log** while the COM call itself completes normally. Without checking,
a workbook whose refresh silently failed would be exported and published
as a current report — stale numbers that look fresh, which is worse than
an outright failure. The worker classifies the trace log and fails the
execution instead.

---

## 4. Authentication scenarios

IBM documents that `Logon` **cannot sign in to cloud-based systems**. The
design therefore does not assume `Logon` works, and `connection_id` on a
report is nullable.

| Scenario | Status | Notes |
|---|---|---|
| Refresh using the PAfE session already established on the worker host | **SUPPORTED** (design); NOT VERIFIED against live PAfE | The default. `auth_mode: existing_pafe_session` |
| On-prem TM1 via `Logon(url, user, password, namespace)` | **REQUIRES CUSTOMER CONFIGURATION** | Credentials must be placed in the worker's *local* credential store. PA-Copilot never sends them |
| PA as a Service / cloud-hosted | **NOT SUPPORTED** by `Logon` | IBM documents this limitation. Use an existing signed-in session on the host |
| SSO via `LogonSSO(...)` | **NOT YET VERIFIED** | The API is wrapped but no code path calls it; it needs an SSO-enabled host to validate |
| Any refresh against a real PAfE install | **NOT VERIFIED** | No PAfE available on the development machine |

> **TM1 credentials are never placed in a job payload.** The worker
> receives non-secret connection coordinates only (address, port, ssl,
> tenant, database). This is asserted by a test.

---

## 5. Register a worker

1. In PA-Copilot: **Report Workers → Register worker**. Requires
   `workers.manage`.
2. Copy the enrollment token. **It is shown once**, is single-use, and
   expires (default 60 minutes).

## 6. Enroll and start the worker

```powershell
pa-worker enroll --server https://pa-copilot.example.com --token pacw-enroll-...
pa-worker diagnostics     # verify Excel + PAfE before running anything
pa-worker start
```

`enroll` probes the host first and reports only the capabilities it could
actually verify. A worker that cannot prove `pafe_automation` is never
given a PAfE job — the control plane refuses at queue time with a
specific error rather than letting the job sit until it times out.

Other commands:

| Command | Purpose |
|---|---|
| `pa-worker status` | Local process state + what the server thinks |
| `pa-worker stop` | Graceful stop; finishes the job in flight |
| `pa-worker diagnostics [--json]` | Probe Excel, PAfE, PDF export |
| `pa-worker test-report [--wait 60]` | **POC mode** — claim and run exactly one job, verbosely, then exit |

## 7-9. Upload a workbook, create a report, run it

**Reports → New report** uploads a `.xlsx`/`.xlsm`/`.xlsb`, then creates
a report against it. **Run now** requires `reports.execute`.

Uploads are validated by container magic number, not by filename or
content-type — both of which the caller controls. The filename is
sanitized for storage and is *never* used to build a path on the worker,
which names files after the execution UUID.

## 10. Retrieve artifacts

**Executions →** select a run **→ Download**. Downloads re-check
permission and organization ownership on every request. There is no
signed URL: an artifact id that leaks is not a capability.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pafe_not_installed` | COM add-in `CognosOffice12.Connect` not registered | Install/repair PAfE. Verify with `pa-worker diagnostics` |
| `pafe_api_unavailable` | Add-in present but disabled, or automation object missing | Enable the add-in in Excel; check PAfE version |
| `excel_launch_failed` | No desktop session, or Excel not installed | Run the worker in an interactive session |
| `workbook_checksum_mismatch` | Bytes changed in transit or at rest | Re-upload the workbook |
| `execution_timeout` | Refresh exceeded the limit | Raise `REPORT_EXECUTION_TIMEOUT_SECONDS`, or check TM1 load |
| `tm1_connection_failed` / `tm1_auth_failed` | Detected from IBM's trace log | Check the PAfE session on the worker host |
| PDF export fails | No printer driver | Install one, or use XLSX output |
| Worker shows OFFLINE | No heartbeat for 3 intervals | Check `pa-worker status` and the worker log |
| Job never claimed | No worker has the required capabilities | `pa-worker diagnostics` on the host |

Every execution carries a `correlation_id` shared across retries. Both
sides log it, so one report run is followable end to end.

---

## 12. Security

### What is enforced

- **Tenancy**: every table has a non-null `organization_id`; a worker's
  organization is resolved from its credential, never from the request.
- **Worker identity**: single-use expiring enrollment token → long-lived
  credential (stored as an HMAC-SHA256 digest keyed with `SECRET_KEY`) →
  short-lived JWT (15 min) carrying a `secret_version`. Rotation
  invalidates every token in flight with no revocation table.
- **Token family separation**: worker tokens and user tokens are signed
  with the same key, so a `type` claim separates them. Tested in both
  directions.
- **No arbitrary code**: the job payload carries an allowlisted verb and
  typed data. No field reaches `Application.Run`, a shell, or a path.
- **Excel cleanup ownership**: forced termination targets only the
  `(pid, create_time)` pair the worker started. If ownership cannot be
  proved, **nothing is terminated** — a stale Excel is preferable to
  killing a user's session.
- **Redaction**: worker logs redact credentials by value shape *and* by
  key name, recursively through diagnostics blobs.

### Known security limitations (POC)

1. **No rate limiting on the worker plane.** `/worker/*` is authenticated
   but unthrottled; a compromised credential could poll aggressively.
2. **Artifacts are stored in PostgreSQL** (`report_blobs`). Appropriate
   for POC scale, not for large or numerous artifacts. The
   `StorageBackend` interface exists so S3 is a swap, not a rewrite.
3. **Credential file ACL is best-effort.** `icacls` failure logs a
   warning rather than refusing to run.
4. **TLS verification can be disabled** (`--insecure`) for local
   development. Never use it against a real deployment.
5. **No signed download URLs.** Every download is a live authenticated
   request — deliberate, but it means no CDN offload.

---

## 13. Known IBM limitations

1. **`Logon` cannot sign in to cloud-based systems** (IBM-documented).
2. **`Wait()` cannot be cancelled.** It blocks until the refresh
   completes. The worker's subprocess isolation is a workaround, not a
   fix — there is no in-process way to bound it.
3. **No type library is installed**, so all COM calls are late-bound.
   Errors surface at runtime, which is why every call is wrapped and
   classified.
4. **Batch mode differs from interactive mode.** IBM notes automation
   behaves differently when the Office app is closed.
5. **A clean `RefreshAllData()` does not prove data arrived** — see §3.

---

## 14. Known PA-Copilot limitations

1. **Excel COM in Session 0 is not supported.** Running the worker as a
   plain Windows service will fail. Use a logged-in session or an
   auto-logon kiosk account. Not solved here.
2. **The stale-execution reaper runs opportunistically** on worker claim,
   not on a timer. With no worker ever polling, a queued execution is not
   reaped until one does. Phase 3's scheduler fixes this.
3. **One job at a time per worker.** No concurrency within a worker.
4. **No scheduling, no email delivery, no AI drafting, no STET approval
   workflow, no native TM1 reporting.** Deliberately out of scope for
   this phase — the columns are reserved, the behaviour is not built.
5. **`.xls` (legacy OLE2) is rejected.** Save as `.xlsx`/`.xlsm`.

---

## Verification status

| Capability | Status |
|---|---|
| Migration applies, downgrades, re-applies | **VERIFIED** |
| Control plane API (32 endpoints) | **VERIFIED** — 45 integration + red-team tests |
| Tenant isolation, worker auth, credential rotation | **VERIFIED** |
| Atomic claim / no double-claim | **VERIFIED** |
| Idempotency (run-now, artifact upload, completion) | **VERIFIED** |
| Real Excel: launch, ownership, cleanup, no ghost process | **VERIFIED** — 11 real-Excel tests |
| Real Excel: workbook open, XLSX save, PDF export | **VERIFIED** |
| Worker enrollment against a live server | **VERIFIED** |
| Capability gating refuses jobs a host cannot run | **VERIFIED** (live) |
| PAfE detection reports absence correctly | **VERIFIED** (this host has no PAfE) |
| `RefreshAllData()` / `Wait()` / `TraceLog()` against real PAfE | **NOT VERIFIED** |
| Refresh against a real TM1 server | **NOT VERIFIED** |
| `Logon` / `LogonSSO` against a real PA server | **NOT VERIFIED** |
| End-to-end SUCCEEDED with a real PAfE refresh | **NOT VERIFIED** |

> PA-Copilot uses IBM's supported Planning Analytics for Microsoft Excel
> automation capabilities. Customer environments may have additional
> Microsoft Office, PAfE, authentication, security, and licensing
> requirements.
