"""PA-Copilot Report Automation — cloud control plane.

DEVELOPER PREVIEW / POC.

This package owns the *control plane* only: report definitions, workbook
custody, worker identity, execution records, and artifacts. It never runs
Microsoft Excel or PAfE — that happens on a customer-operated Windows
worker (see the `worker/` directory at the repository root), which makes
outbound calls to the endpoints in `src/api/v1/worker.py`.

The split is deliberate and load-bearing: Excel automation takes minutes,
holds a desktop session, and only runs on Windows. Nothing in this package
may block an HTTP request or a database connection on it.
"""
