"""What each AI tool is, as the application sees it.

The registry says which tools exist. This module says what each one *is*:
its category, whether it reads, validates, drafts a write or drafts an
execution, where its answer comes from, and which of its inputs name the
object it acts on. The UI shows these on every tool call, the audit row
records them, and the catalog in docs/TM1_TOOL_CATALOG.md is generated
from them.

Two rules the tests enforce:

1. **Every registered tool is classified here.** A tool missing from this
   table cannot be shown honestly to a user, so the build fails instead.
2. **No AI tool mutates TM1.** Anything above VALIDATE is a *proposal*: its
   name starts with `propose_`, it writes a draft row, and the TM1 effect
   happens only when a person approves the draft through the change API.
   `requires_confirmation` is therefore true exactly for those tools.

Classification is owned by the application, like planning_analytics/risk.py:
it is never read from a tool's own description and never decided by the
model.
"""

from dataclasses import dataclass
from enum import Enum


class ToolAccess(str, Enum):
    #: Reads model structure, data or logs.
    READ = "READ"
    #: Checks code against TM1 or a reference without saving anything.
    VALIDATE = "VALIDATE"
    #: Drafts a change to model objects. Applied only on human approval.
    WRITE = "WRITE"
    #: Drafts a process run. Performed only on human approval.
    EXECUTE = "EXECUTE"
    #: Security or server administration. No AI tool has this class.
    ADMIN = "ADMIN"


class EvidenceKind(str, Enum):
    #: Read from the TM1 server during this call.
    LIVE = "live"
    #: Deterministic analysis of objects read live (a parser, not a guess).
    ANALYSIS = "analysis"
    #: The extracted metadata graph: correct as of the last extraction.
    SNAPSHOT = "snapshot"
    #: The function reference, learned standards or the knowledge base.
    REFERENCE = "reference"
    #: A draft row written for human review; nothing on the server changed.
    DRAFT = "draft"


@dataclass(frozen=True)
class ToolClassification:
    category: str
    access: ToolAccess
    #: Human-readable source, shown under "Evidence" in the UI.
    evidence: str
    evidence_kind: EvidenceKind
    #: Inputs that name the object acted on, in display order.
    target_keys: tuple[str, ...] = ()

    @property
    def requires_confirmation(self) -> bool:
        return self.access in (ToolAccess.WRITE, ToolAccess.EXECUTE, ToolAccess.ADMIN)


R, V, W, X = ToolAccess.READ, ToolAccess.VALIDATE, ToolAccess.WRITE, ToolAccess.EXECUTE
LIVE, ANALYSIS, SNAPSHOT, REFERENCE, DRAFT = (
    EvidenceKind.LIVE,
    EvidenceKind.ANALYSIS,
    EvidenceKind.SNAPSHOT,
    EvidenceKind.REFERENCE,
    EvidenceKind.DRAFT,
)


def _c(category, access, evidence, kind, *targets) -> ToolClassification:
    return ToolClassification(category, access, evidence, kind, tuple(targets))


CLASSIFICATION: dict[str, ToolClassification] = {
    # --- Discovery: what is in the model ---
    "list_cubes": _c("discovery", R, "TM1 REST · cubes", LIVE),
    "get_cube": _c("discovery", R, "TM1 REST · cube metadata", LIVE, "cube_name"),
    "get_cube_rules": _c("discovery", R, "TM1 REST · rule text", LIVE, "cube_name"),
    "list_dimensions": _c("discovery", R, "TM1 REST · dimensions", LIVE),
    "get_dimension": _c("discovery", R, "TM1 REST · dimension metadata", LIVE, "dimension_name"),
    "list_dimension_elements": _c("discovery", R, "TM1 REST · elements", LIVE, "dimension_name", "hierarchy_name"),
    "list_processes": _c("discovery", R, "TM1 REST · processes", LIVE),
    "get_process": _c("discovery", R, "TM1 REST · process source", LIVE, "process_name"),
    "list_chores": _c("discovery", R, "TM1 REST · chores", LIVE),
    "get_chore": _c("discovery", R, "TM1 REST · chore schedule", LIVE, "chore_name"),
    "list_cube_views": _c("discovery", R, "TM1 REST · views", LIVE, "cube_name"),
    "get_view": _c("discovery", R, "TM1 REST · view definition", LIVE, "cube_name", "view_name"),
    "list_dimension_subsets": _c("discovery", R, "TM1 REST · subsets", LIVE, "dimension_name"),
    "get_subset": _c("discovery", R, "TM1 REST · subset definition", LIVE, "dimension_name", "subset_name"),
    "get_dimension_attributes": _c("discovery", R, "TM1 REST · attribute definitions", LIVE, "dimension_name"),
    "get_element_context": _c("discovery", R, "TM1 REST · element, parents, attributes", LIVE, "dimension_name", "element_name"),
    "get_server_state": _c("discovery", R, "TM1 REST · server, sessions, threads", LIVE),
    # --- Exploration: find things and follow references ---
    "search_model_objects": _c("exploration", R, "TM1 REST · object names", LIVE, "query"),
    "search_process_code": _c("exploration", R, "TM1 REST · process source", LIVE, "search_string"),
    "search_rules": _c("exploration", R, "TM1 REST · rule text", LIVE, "search_string"),
    "analyze_process_references": _c("exploration", R, "TI parser over live process source", ANALYSIS, "process_name"),
    "get_process_call_tree": _c("exploration", R, "TI parser over live process source", ANALYSIS, "process_name"),
    "get_cube_data_flow": _c("exploration", R, "Metadata graph or TI parser over live source", ANALYSIS, "cube_name"),
    # --- Dependencies: the extracted graph ---
    "get_cube_dependencies": _c("dependencies", R, "Metadata graph", SNAPSHOT, "cube_name"),
    "get_dimension_dependents": _c("dependencies", R, "Metadata graph", SNAPSHOT, "dimension_name"),
    "get_model_changes": _c("governance", R, "Metadata extraction history", SNAPSHOT),
    "search_engineering_memory": _c("knowledge", R, "Approved engineering memory", REFERENCE, "query"),
    "get_monitor_alerts": _c("governance", R, "Alerts raised by monitoring rules", REFERENCE),
    "propose_monitor": _c("governance", W, "Monitoring rule proposal for the user to turn on", DRAFT, "kind"),
    "investigate_incident": _c("diagnostics", R, "Changes, runs, model differences, rules and alerts near the reported object", ANALYSIS, "cube_name"),
    "get_work_item": _c("knowledge", R, "Team work item and its linked records", REFERENCE, "reference"),
    "propose_engineering_memory": _c("knowledge", W, "Memory proposal for human approval", DRAFT, "object_name"),
    "get_model_health": _c("governance", R, "Scored health scans (rule parser + TI review at scan time)", ANALYSIS),
    "get_performance_report": _c("diagnostics", R, "Process run history from TM1's message log", LIVE),
    "analyze_change_impact": _c("dependencies", R, "Metadata graph, ranked by severity rules", SNAPSHOT, "object_type", "name"),
    "get_object_relationships": _c("dependencies", R, "Metadata graph", SNAPSHOT, "object_type", "name"),
    "find_dependents": _c("dependencies", R, "Metadata graph", SNAPSHOT, "object_type", "name"),
    "find_dependencies": _c("dependencies", R, "Metadata graph", SNAPSHOT, "object_type", "name"),
    "dependency_path": _c("dependencies", R, "Metadata graph", SNAPSHOT, "from_name", "to_name"),
    "find_unused_objects": _c("governance", R, "Metadata graph", SNAPSHOT, "object_type"),
    # --- Cells ---
    "execute_mdx": _c("cells", R, "TM1 REST · MDX cellset", LIVE),
    "show_chart": _c("cells", R, "TM1 REST · MDX cellset", LIVE),
    "get_query_context": _c("discovery", R, "TM1 REST · dimension levels", LIVE, "cube_name"),
    "find_data": _c("cells", R, "TM1 REST · MDX cellset", LIVE, "cube_name"),
    "query_cube": _c("cells", R, "TM1 REST · MDX cellset", LIVE, "cube_name"),
    "get_cell_values": _c("cells", R, "TM1 REST · cell values", LIVE, "cube_name"),
    "inspect_cell": _c("cells", R, "TM1 REST · cell properties + rule parser", LIVE, "cube_name"),
    "trace_cell_calculation": _c("cells", R, "Rule parser over live rule text", ANALYSIS, "cube_name"),
    "analyze_cube_rules": _c("governance", R, "Rule parser over live rule text", ANALYSIS, "cube_name"),
    "audit_model_rules": _c("governance", R, "Rule parser over live rule text", ANALYSIS),
    "run_model_health_check": _c("governance", R, "Rule parser + TI analysers over live source", ANALYSIS),
    # --- Diagnostics ---
    "get_message_log": _c("diagnostics", R, "TM1 REST · message log", LIVE),
    "get_transaction_log": _c("diagnostics", R, "TM1 REST · transaction log", LIVE, "cube"),
    "list_process_error_logs": _c("diagnostics", R, "TM1 REST · error log files", LIVE, "process_name"),
    "get_process_error_log": _c("diagnostics", R, "TM1 REST · process error log", LIVE, "process_name", "file_name"),
    "map_log_error_to_code": _c("diagnostics", R, "Process error log + process source", LIVE, "process_name"),
    "get_process_execution_history": _c("diagnostics", R, "TM1 REST · message log (TM1.Process)", LIVE, "process_name"),
    "diagnose_process_failure": _c("diagnostics", R, "Process source, error log, message log, live checks", LIVE, "process_name"),
    "get_change_status": _c("change_management", R, "PA-Copilot change records", REFERENCE, "change_id", "target_name"),
    # --- Development ---
    "diff_process": _c("development", R, "TM1 REST · process source", LIVE, "process_name"),
    "validate_process_code": _c("development", V, "TM1 compile (unsaved) + static analysis", LIVE, "process_name"),
    "review_process_code": _c("development", R, "Static analysis + function reference", ANALYSIS, "process_name"),
    "lookup_tm1_function": _c("development", R, "TM1 function reference", REFERENCE, "query"),
    "check_tm1_code": _c("development", R, "TM1 function reference", REFERENCE),
    # --- Change management (drafts only) ---
    "propose_rule_update": _c("change_management", W, "Draft for human review", DRAFT, "cube_name"),
    "propose_cell_write": _c("change_management", W, "Cell write draft for human review", DRAFT, "cube_name"),
    "propose_process_update": _c("change_management", W, "Draft for human review", DRAFT, "process_name"),
    "propose_process_copy": _c("change_management", W, "Draft for human review", DRAFT, "source_process", "new_process_name"),
    # --- Execution (drafts only) ---
    "propose_process_run": _c("execution", X, "Draft for human approval", DRAFT, "process_name"),
    # --- Knowledge ---
    "search_knowledge_base": _c("knowledge", R, "Organization knowledge base", REFERENCE, "query"),
}


def classification_for(name: str) -> ToolClassification | None:
    return CLASSIFICATION.get(name)
