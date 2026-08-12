"""Product self-knowledge, generated from the capability registry.

Without this the assistant has no grounding for questions about the
application it is embedded in. Asked "what are Reports and Report
Workers?" — both visible in the navigation — it searched the knowledge
base, found nothing (these are product features, not customer documents)
and gave up.

The capability section is **generated from `capabilities.py`** rather
than hand-maintained. A hand-written list drifts: a feature ships, or is
disabled, or turns out not to work, and the prose keeps confidently
describing the old world. Generating it means the prompt cannot disagree
with the registry, and the registry is the thing a human updates
deliberately.

Three constraints hold:

* **Stable.** Prompt caching is a byte-exact prefix match, so this block
  must contain nothing organization-, user- or question-specific. It is
  built once at import.

* **Descriptive, not enabling.** Nothing here grants a capability. The
  assistant can explain a feature and point at a screen; it has no tool
  to create a report, start one, or register a worker. The boundary is
  enforced by the absence of tools — this text just stops it offering.

* **PLANNED is never described as usable.** A model asked "can you
  schedule this weekly?" will otherwise fill the gap with what reporting
  products normally do. Naming the unbuilt features explicitly, under a
  heading that says they do not work, is what prevents that.
"""

from src.ai.capabilities import CAPABILITIES, CapabilityStatus

_NAVIGATION = """\
PA-Copilot is an AI platform for IBM Planning Analytics / TM1. The left-\
hand navigation contains: Dashboard, TM1 Connections, AI Chat, Knowledge \
Base, Coding Standards, Metadata Explorer, Visualize, Deployments, \
Reports, Report Workers, Executions, Monitoring, Users, Settings."""

_BOUNDARY = """\
What you can and cannot do:

You can explain any of the above and point users to the right screen. You \
cannot create reports, start executions, register workers, deploy TM1 \
changes, or send anything — you have no tool for those. They are \
deliberate human actions, gated by permissions. If asked to perform one, \
say so plainly and describe where the user can do it themselves.

Never describe anything under NOT CURRENTLY AVAILABLE as though it works, \
and never imply that one capability being available means a related one \
is. A worker being online does not mean reports can be emailed; a Reports \
screen existing does not mean schedules can be created."""


def _render_group(
    heading: str,
    statuses: tuple[CapabilityStatus, ...],
    *,
    preview: bool = False,
    unavailable: bool = False,
) -> str | None:
    items = [c for c in CAPABILITIES if c.status in statuses]

    if not items:
        return None

    lines = [heading]

    for capability in items:
        line = f"- {capability.name}: {capability.summary}"

        if preview:
            # Required by the consistency tests: a preview capability is
            # never described without the words that mark it as one.
            line += (
                " (DEVELOPER PREVIEW — not validated end-to-end; do not "
                "rely on it for production reporting.)"
            )

        if capability.permission and not unavailable:
            line += f" Requires the {capability.permission} permission."

        if capability.caveat:
            line += f" {capability.caveat}"

        lines.append(line)

    return "\n".join(lines)


def _build_overview() -> str:
    sections: list[str] = [
        "About PA-Copilot (the application you are part of):",
        _NAVIGATION,
        "",
        "PA-COPILOT PRODUCT CAPABILITIES",
    ]

    available = _render_group(
        "AVAILABLE (these work today):",
        (CapabilityStatus.AVAILABLE,),
    )

    preview = _render_group(
        "DEVELOPER PREVIEW (implemented, not yet validated end-to-end):",
        (CapabilityStatus.DEVELOPER_PREVIEW,),
        preview=True,
    )

    # PLANNED, DISABLED and DEPRECATED collapse into one heading on
    # purpose: from the user's point of view the answer to "can I do
    # this?" is the same "no", and three near-identical headings invite
    # the model to treat one of them as a soft yes.
    unavailable = _render_group(
        "NOT CURRENTLY AVAILABLE (these do NOT work — say so plainly):",
        (
            CapabilityStatus.PLANNED,
            CapabilityStatus.DISABLED,
            CapabilityStatus.DEPRECATED,
        ),
        unavailable=True,
    )

    for section in (available, preview, unavailable):
        if section:
            sections.extend(["", section])

    sections.extend(["", _BOUNDARY])

    return "\n".join(sections)


#: Built once at import — stable for the life of the process, which is
#: what keeps the cached prompt prefix byte-identical.
PRODUCT_OVERVIEW = _build_overview()
