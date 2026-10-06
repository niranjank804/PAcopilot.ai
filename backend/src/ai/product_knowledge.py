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
Base, Engineering Memory, Team, Metadata Explorer, Visualize, Deployments, \
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
            # never described without the words that mark it as one — on
            # its own line, so the marker travels with the capability if
            # the model quotes one in isolation.
            #
            # Kept terse deliberately. This repeats verbatim on every
            # preview line under a heading that already says the same
            # thing, so each word costs once per preview capability in a
            # block prepended to every request. The heading carries the
            # explanation; the line carries the label.
            line += " (DEVELOPER PREVIEW — not validated; don't rely on it.)"

        if capability.permission and not unavailable:
            line += f" Requires the {capability.permission} permission."

        if capability.caveat:
            line += f" {capability.caveat}"

        lines.append(line)

    return "\n".join(lines)


#: How every reply should sound. Answers read like reports — headings,
#: bullet lists, bold labels — when people wanted to be talked to, and
#: many of them listen: replies are read aloud after a spoken question,
#: and "Can you hear me?" was once answered with an explanation of TM1.
#: Kept apart from the capability registry below, whose size budget is
#: about the registry, not about tone.
CONVERSATION_STYLE = (
    "HOW TO TALK: Write the way a helpful colleague talks — natural, warm, "
    "plain sentences, and no jargon the person has not used. Lead with the "
    "answer in a sentence or two, then add only the detail they need. Use "
    "headings, bullet lists or tables only when the content really is a "
    "list, a sequence of steps or a comparison; put code in code blocks. "
    "Many people speak to you through the microphone and hear your reply "
    "read aloud, so keep sentences short and easy to say. Answer greetings "
    "and small talk like a person, in one friendly line that invites the "
    "request — e.g. \"Can you hear me?\" → \"Yes, I can hear you. How can "
    "I help you today?\" — without listing what you can do or calling "
    "tools. If a transcript is garbled or repeats itself, answer what the "
    "person evidently meant, or ask them to repeat it."
)


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
CAPABILITY_OVERVIEW = _build_overview()

#: What every chat begins with: how to talk, then what the product is.
PRODUCT_OVERVIEW = f"{CONVERSATION_STYLE}\n\n{CAPABILITY_OVERVIEW}"
