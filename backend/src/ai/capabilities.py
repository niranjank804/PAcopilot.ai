"""Explicit registry of what PA-Copilot can actually do today.

The rule this module exists to enforce: **commercial availability is a
decision, not an artifact of the codebase.** A table exists, an endpoint
responds, a directory is present — none of that means a customer can use
a feature. `report_executions` had a table, a migration, five endpoints
and a passing test suite for a capability nobody has yet proved works
against real PAfE. Inferring "available" from any of those would make the
assistant confidently wrong about the product.

So status is declared here by a human, and everything else — the AI's
product knowledge, the consistency tests — is derived from it. When a
capability's real status changes, this file changes, and the generated
prompt follows.

`implementation` is a pointer to where the capability actually lives. It
is asserted to exist for anything claimed AVAILABLE or
DEVELOPER_PREVIEW, so a capability cannot be marked shippable while
pointing at code that was never written or has since been deleted.
"""

from dataclasses import dataclass
from enum import Enum


class CapabilityStatus(str, Enum):
    #: Generally available. The assistant may describe it as usable now.
    AVAILABLE = "AVAILABLE"

    #: Implemented and reachable, but not validated end-to-end or not
    #: contractually supported. Must always be described with preview
    #: language so nobody plans around it.
    DEVELOPER_PREVIEW = "DEVELOPER_PREVIEW"

    #: Intended, not built. The assistant must state plainly that it does
    #: not work yet — never describe it as usable.
    PLANNED = "PLANNED"

    #: Built, but switched off in this deployment.
    DISABLED = "DISABLED"

    #: Still present, going away. Describe, but steer users off it.
    DEPRECATED = "DEPRECATED"


#: Statuses a user can actually act on today.
USABLE_STATUSES = frozenset(
    {CapabilityStatus.AVAILABLE, CapabilityStatus.DEVELOPER_PREVIEW}
)


@dataclass(frozen=True)
class Capability:
    key: str
    name: str
    status: CapabilityStatus
    summary: str

    #: Repository-relative path proving the capability exists. Required
    #: for AVAILABLE and DEVELOPER_PREVIEW; omitted for PLANNED, which by
    #: definition has no implementation.
    implementation: str | None = None

    #: Permission code gating the primary action, if any. Asserted to
    #: exist in scripts/seed_permissions.py — the assistant must never
    #: tell a user to request a permission that was never created.
    permission: str | None = None

    #: Extra caveat appended verbatim to the generated prompt.
    caveat: str | None = None


# ----------------------------------------------------------------------
# The registry
#
# Statuses below were determined by inspecting this repository, not by
# copying the example in the phase brief.
# ----------------------------------------------------------------------

CAPABILITIES: tuple[Capability, ...] = (
    # --- Generally available: shipped, validated, in use ---
    Capability(
        key="tm1_connections",
        name="TM1 connections",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Register, test and manage connections to TM1 / Planning "
            "Analytics servers, on-prem or PA as a Service."
        ),
        implementation="backend/src/tm1/service.py",
        permission="tm1.write",
    ),
    Capability(
        key="ai_chat",
        name="AI chat with specialist agents",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Ask questions about TM1 models, grounded in live metadata. "
            "Specialist agents cover analysis, development, TI, "
            "troubleshooting, review, architecture and documentation."
        ),
        implementation="backend/src/ai/orchestrator.py",
        permission="ai.chat",
    ),
    Capability(
        key="knowledge_base",
        name="Knowledge base",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Upload organizational documents that ground the assistant's "
            "answers, with citations."
        ),
        implementation="backend/src/knowledge/service.py",
        permission="knowledge.write",
    ),
    Capability(
        key="metadata_explorer",
        name="Metadata explorer",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Explore the dependency graph of cubes, dimensions, processes "
            "and rules, including impact analysis."
        ),
        implementation="backend/src/tm1/metadata/dependency_analyzer.py",
        permission="tm1.read",
    ),
    Capability(
        key="visualize",
        name="Visualize",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Turn natural-language questions into charts backed by live "
            "cube data."
        ),
        implementation="backend/src/ai/visualization.py",
        permission="tm1.read",
    ),
    Capability(
        key="stet_deployments",
        name="STET change drafts",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Proposed TM1 changes (rules, TurboIntegrator processes) are "
            "held as drafts with impact analysis until a human with deploy "
            "rights executes them. AI can draft; only a person deploys."
        ),
        implementation="backend/src/tm1/deployment/change_service.py",
        permission="tm1.deploy",
    ),
    Capability(
        key="coding_standards",
        name="Coding standards",
        status=CapabilityStatus.AVAILABLE,
        summary=(
            "Organizational TM1 conventions, applied when generating or "
            "reviewing code."
        ),
        implementation="backend/src/database/models/tm1_coding_convention.py",
        permission="tm1.read",
    ),
    # --- Developer preview: built, reachable, NOT validated end-to-end ---
    #
    # Every report-automation capability sits here because the PAfE
    # execution primitive has not been proven against a real PAfE
    # install. The control plane, worker, Excel automation and artifact
    # handling are implemented and tested; the IBM PAfE refresh itself is
    # unverified, so nothing here may be described as production-usable.
    Capability(
        key="report_workbook_upload",
        name="PAfE workbook upload",
        status=CapabilityStatus.DEVELOPER_PREVIEW,
        summary=(
            "Upload and version PAfE workbooks (.xlsx/.xlsm/.xlsb) with "
            "checksum verification."
        ),
        implementation="backend/src/reports/workbook_service.py",
        permission="reports.create",
    ),
    Capability(
        key="report_definitions",
        name="Reports",
        status=CapabilityStatus.DEVELOPER_PREVIEW,
        summary=(
            "Define a report as a PAfE workbook plus the output formats "
            "wanted (XLSX, PDF)."
        ),
        implementation="backend/src/reports/report_service.py",
        permission="reports.create",
    ),
    Capability(
        key="windows_worker",
        name="Report workers",
        status=CapabilityStatus.DEVELOPER_PREVIEW,
        summary=(
            "Register customer-operated Windows machines running Excel and "
            "PAfE. They connect outbound only; PA-Copilot never dials into "
            "the customer network, and Excel never runs in the cloud."
        ),
        implementation="backend/src/reports/worker_service.py",
        permission="workers.manage",
        caveat=(
            "Requires an interactive Windows session — Excel COM "
            "automation is not supported in Session 0, so the worker "
            "cannot run as a plain Windows service."
        ),
    ),
    Capability(
        key="report_execution",
        name="Report execution (Run now)",
        status=CapabilityStatus.DEVELOPER_PREVIEW,
        summary=(
            "Run a report on demand. A worker claims it, refreshes the "
            "workbook through IBM's PAfE automation API, exports the "
            "output and uploads it. Executions record status, duration, "
            "worker, retries and errors."
        ),
        implementation="backend/src/reports/execution_service.py",
        permission="reports.execute",
        caveat=(
            "The PAfE refresh itself has NOT yet been validated against a "
            "real Planning Analytics for Microsoft Excel installation."
        ),
    ),
    Capability(
        key="report_artifacts",
        name="Report artifacts",
        status=CapabilityStatus.DEVELOPER_PREVIEW,
        summary=(
            "Download the files an execution produced. Access is "
            "re-checked per request; an artifact id is not a shareable "
            "link."
        ),
        implementation="backend/src/reports/artifact_service.py",
        permission="reports.read",
    ),
    # --- Planned: NOT built. Must never be described as usable. ---
    Capability(
        key="report_scheduling",
        name="Recurring report schedules",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Running reports automatically on a daily/weekly/monthly "
            "schedule."
        ),
    ),
    Capability(
        key="email_delivery",
        name="Email delivery of reports",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Sending report output to recipients by email, as an "
            "attachment or a secure link."
        ),
    ),
    Capability(
        key="stet_schedule_approval",
        name="STET approval for schedules",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Requiring human approval before a report schedule becomes "
            "active."
        ),
    ),
    Capability(
        key="ai_report_drafting",
        name="AI-generated report schedules",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Asking the assistant to draft a report definition or schedule "
            "from a natural-language request."
        ),
    ),
    Capability(
        key="report_bursting",
        name="Report bursting",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Producing per-recipient variants of one report from a single "
            "definition."
        ),
    ),
    Capability(
        key="native_tm1_reporting",
        name="Native TM1 report generation",
        status=CapabilityStatus.PLANNED,
        summary=(
            "Generating reports directly from TM1 (MDX, Quick Reports, "
            "Explorations, Dynamic Reports) without a PAfE workbook or "
            "Excel."
        ),
    ),
)


CAPABILITIES_BY_KEY = {capability.key: capability for capability in CAPABILITIES}


def by_status(status: CapabilityStatus) -> tuple[Capability, ...]:
    return tuple(item for item in CAPABILITIES if item.status is status)


def is_usable(key: str) -> bool:
    """Whether a capability can be acted on today."""

    capability = CAPABILITIES_BY_KEY.get(key)

    return capability is not None and capability.status in USABLE_STATUSES
