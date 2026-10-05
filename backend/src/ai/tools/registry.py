from src.ai.tools.base import Tool
from src.ai.tools.knowledge import SearchKnowledgeBaseTool
from src.ai.tools.tm1.analysis import (
    DependencyPathTool,
    FindDependenciesTool,
    FindDependentsTool,
    AnalyzeChangeImpactTool,
    FindUnusedObjectsTool,
    GetModelChangesTool,
)
from src.ai.tools.tm1.cells import ExecuteMDXTool, GetCellValuesTool, InspectCellTool
from src.ai.tools.tm1.chart import ShowChartTool
from src.ai.tools.tm1.query import FindDataTool, GetQueryContextTool, QueryCubeTool
from src.ai.tools.tm1.changes import (
    ProposeProcessCopyTool,
    ProposeProcessRunTool,
    ProposeProcessUpdateTool,
    ProposeRuleUpdateTool,
)
from src.ai.tools.memory import ProposeEngineeringMemoryTool, SearchEngineeringMemoryTool
from src.ai.tools.work_items import GetWorkItemTool
from src.ai.tools.monitors import GetMonitorAlertsTool, ProposeMonitorTool
from src.ai.tools.tm1.intelligence import GetModelHealthTool, GetPerformanceReportTool
from src.ai.tools.tm1.development import ReviewProcessCodeTool, ValidateProcessCodeTool
from src.ai.tools.tm1.diagnostics import (
    DiagnoseProcessFailureTool,
    GetChangeStatusTool,
    GetProcessExecutionHistoryTool,
)
from src.ai.tools.tm1.explore import (
    AnalyzeProcessReferencesTool,
    GetCubeDataFlowTool,
    GetProcessCallTreeTool,
    SearchModelObjectsTool,
)
from src.ai.tools.tm1.chores import GetChoreTool, ListChoresTool
from src.ai.tools.tm1.cubes import GetCubeRulesTool, GetCubeTool, ListCubesTool
from src.ai.tools.tm1.dimensions import (
    GetDimensionTool,
    ListDimensionElementsTool,
    ListDimensionsTool,
)
from src.ai.tools.tm1.functions import (
    CheckTM1CodeTool,
    LookupTM1FunctionTool,
)
from src.ai.tools.tm1.metadata import (
    GetCubeDependenciesTool,
    GetDimensionDependentsTool,
    GetObjectRelationshipsTool,
)
from src.ai.tools.tm1.health import RunModelHealthCheckTool
from src.ai.tools.tm1.logs import (
    GetMessageLogTool,
    GetProcessErrorLogTool,
    GetTransactionLogTool,
    ListProcessErrorLogsTool,
    MapLogErrorToCodeTool,
)
from src.ai.tools.tm1.processes import (
    DiffProcessTool,
    GetProcessTool,
    ListProcessesTool,
    SearchProcessCodeTool,
)
from src.ai.tools.tm1.rules import (
    AnalyzeCubeRulesTool,
    AuditModelRulesTool,
    SearchRulesTool,
    TraceCellCalculationTool,
)
from src.ai.tools.tm1.standards import GetCodingStandardsTool
from src.ai.tools.tm1.structure import (
    GetDimensionAttributesTool,
    GetElementContextTool,
    GetServerStateTool,
    GetSubsetTool,
    GetViewTool,
    ListCubeViewsTool,
    ListDimensionSubsetsTool,
)

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        ListCubesTool(),
        GetCubeTool(),
        GetCubeRulesTool(),
        ListDimensionsTool(),
        GetDimensionTool(),
        ListDimensionElementsTool(),
        ExecuteMDXTool(),
        ShowChartTool(),
        GetQueryContextTool(),
        FindDataTool(),
        QueryCubeTool(),
        GetCellValuesTool(),
        InspectCellTool(),
        ListProcessesTool(),
        GetProcessTool(),
        SearchProcessCodeTool(),
        DiffProcessTool(),
        ListCubeViewsTool(),
        GetViewTool(),
        ListDimensionSubsetsTool(),
        GetSubsetTool(),
        SearchModelObjectsTool(),
        AnalyzeProcessReferencesTool(),
        GetProcessCallTreeTool(),
        GetCubeDataFlowTool(),
        GetDimensionAttributesTool(),
        GetElementContextTool(),
        GetServerStateTool(),
        RunModelHealthCheckTool(),
        AnalyzeCubeRulesTool(),
        TraceCellCalculationTool(),
        SearchRulesTool(),
        AuditModelRulesTool(),
        GetMessageLogTool(),
        GetTransactionLogTool(),
        ListProcessErrorLogsTool(),
        GetProcessErrorLogTool(),
        MapLogErrorToCodeTool(),
        GetProcessExecutionHistoryTool(),
        GetChangeStatusTool(),
        GetModelHealthTool(),
        GetPerformanceReportTool(),
        SearchEngineeringMemoryTool(),
        ProposeEngineeringMemoryTool(),
        GetWorkItemTool(),
        GetMonitorAlertsTool(),
        ProposeMonitorTool(),
        DiagnoseProcessFailureTool(),
        ValidateProcessCodeTool(),
        ReviewProcessCodeTool(),
        ListChoresTool(),
        GetChoreTool(),
        GetCubeDependenciesTool(),
        GetDimensionDependentsTool(),
        GetObjectRelationshipsTool(),
        FindDependentsTool(),
        FindDependenciesTool(),
        DependencyPathTool(),
        FindUnusedObjectsTool(),
        GetModelChangesTool(),
        AnalyzeChangeImpactTool(),
        ProposeRuleUpdateTool(),
        ProposeProcessUpdateTool(),
        ProposeProcessCopyTool(),
        ProposeProcessRunTool(),
        SearchKnowledgeBaseTool(),
        LookupTM1FunctionTool(),
        CheckTM1CodeTool(),
        GetCodingStandardsTool(),
    )
}


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def list_tools() -> list[Tool]:
    return list(TOOLS.values())
