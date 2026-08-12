"""PA-Copilot Report Automation — Windows worker.

DEVELOPER PREVIEW / POC.

This process runs on a customer-operated Windows machine that has
Microsoft Excel and IBM Planning Analytics for Microsoft Excel (PAfE)
installed. It makes only *outbound* HTTPS calls to PA-Copilot: it opens
no listening port, so it needs no inbound firewall rule and is not
reachable from the internet.

Its entire job is to execute allowlisted operations
(`pa_worker.execution.operations`) against workbooks that PA-Copilot
hands it, and to report what happened. It cannot be sent code — see
`pa_worker/execution/operations.py` for the boundary.
"""

__version__ = "0.1.0"
