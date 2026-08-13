# PAfE validation runbook

Everything except the PAfE install is ready on this machine. This is the
shortest path from "installer downloaded" to "acceptance test passed".

## Confirmed ready

| Piece | State |
|---|---|
| Excel | 16.0, COM automation verified |
| TM1 server | `Planning Sample`, HTTPS port **12354** |
| Test cube | `PA_COPILOT_TEST` exists |
| Dimension order | `PA_COPILOT_TEST_Entity`, `PA_COPILOT_TEST_Measure` |
| Test intersection | `TestEntity` / `Value` (currently `222222`) |
| Acceptance test | `worker/tests/test_pafe_live.py`, skips with precise reasons |

## Step 1 — install PAfE

Run `C:\Users\kotes\Downloads\PAfE_Trial_us-east-1.exe`
(IBM-signed, `PAfE-AutoLauncher`).

It may ask for IBM credentials and may start a trial licence clock.

> The XLL files in Downloads are **not** a substitute. Loading
> `IBM_PAfE_x64_3.1.4.10.xll` via `RegisterXLL` registers a
> `CognosOffice12.Connect` entry, but activating it fails with a
> `com_error` and `.Object` is `None`. You get the `DBRW` worksheet
> function without the automation server — which is exactly the half the
> worker cannot use.

## Step 2 — confirm the automation object

```powershell
cd C:\Projects\PA-Copilot\worker
python -m pa_worker diagnostics-pafe
```

Required before anything else is worth trying:

```
VERDICT: INSTALLED_AND_AUTOMATION_AVAILABLE
```

Exit code 0. Anything else names the broken link — `PAFE_NOT_INSTALLED`,
`PAFE_ADDIN_NOT_REGISTERED`, `PAFE_COM_UNAVAILABLE`,
`AUTOMATION_SERVER_UNAVAILABLE`.

## Step 3 — a PAfE workbook bound to the test cube

One cell referencing the test intersection. In Excel with PAfE active,
connect to `Planning Sample`, then in `Sheet1!B2`:

```
=DBRW("Planning Sample:PA_COPILOT_TEST","TestEntity","Value")
```

Element order must match the cube's dimension order above. Save as
`.xlsx` and note the path.

*If PAfE's connection naming differs on your install, build the cell with
the PAfE task pane instead and use whatever formula it produces — the
test only needs the cell to resolve that intersection.*

I can also try to author this workbook programmatically over COM once
PAfE is installed, which would remove this step. Worth attempting before
doing it by hand.

## Step 4 — run the acceptance test

```powershell
cd C:\Projects\PA-Copilot\worker
$env:PA_COPILOT_TM1_ADDRESS  = "localhost"
$env:PA_COPILOT_TM1_PORT     = "12354"
$env:PA_COPILOT_TM1_SSL      = "true"
$env:PA_COPILOT_TM1_USER     = "admin"
$env:PA_COPILOT_TM1_PASSWORD = "<password>"
$env:PA_COPILOT_PAFE_TEST_WORKBOOK = "C:\path\to\PA_Copilot_Test.xlsx"
$env:PA_COPILOT_PAFE_TEST_CELL     = "Sheet1!B2"

pytest tests/test_pafe_live.py -m pafe_live -v
```

## What the test proves

It writes a **fresh random value** to TM1 immediately before the run,
then asserts that exact number appears in the artifact Excel produced.

A fixed sentinel would pass against a workbook that merely had the value
saved in it from last time — which is precisely the "RefreshAllData
returned without exception" false positive this whole exercise exists to
rule out. The random value makes a silently-failed refresh impossible to
mistake for success.

Also asserted: `SuppressMessages → RefreshAllData → Wait` in order, a
TraceLog was captured, no ghost `EXCEL.EXE`, and a bystander Excel
survives cleanup.

## If it fails

The failure message names the gap. The one worth understanding:

```
STALE DATA: artifact shows <x>, TM1 holds <y>. RefreshAllData()/Wait()
completed without error but the workbook did not receive current TM1 data.
```

That is the real finding, not a test bug — it would mean PAfE's refresh
does not do what the whole report-automation design assumes, and the
scheduler must not be built until it is understood.
