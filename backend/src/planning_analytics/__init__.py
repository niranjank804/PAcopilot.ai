"""Provider-neutral Planning Analytics capability layer.

PA-Copilot can reach Planning Analytics through several interfaces that
are genuinely different products, not variants of one thing:

* **Native TM1 REST** — the existing, validated integration (`src/tm1/`).
* **IBM Planning Analytics MCP** — IBM's remote MCP server, optional and
  licence-gated.
* **PAx** — IBM's COM automation API, which only exists on a Windows host
  with the Excel add-in installed.
* **PAfE worker** — PA-Copilot's own Windows worker (`worker/`).

This package adds a thin capability layer *in front of* those, so an
agent asks for a capability ("list cubes") rather than naming a
transport. Nothing here replaces the existing TM1 integration; native
TM1 REST remains the preferred provider and the only validated one.

Scope of this phase is deliberately read-only. No provider here can
write, execute a process, mutate a sandbox, or publish anything — that
is enforced by `risk.py`, not by convention.
"""
