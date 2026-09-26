from src.ai.tools.base import Tool
from src.ai.tools.knowledge import SearchKnowledgeBaseTool
from src.ai.tools.tm1.analysis import (
    DependencyPathTool,
    FindDependenciesTool,
    FindDependentsTool,
    FindUnusedObjectsTool,
)
from src.ai.tools.tm1.cells import ExecuteMDXTool
from src.ai.tools.tm1.chart import ShowChartTool
from src.ai.tools.tm1.changes import (
    ProposeProcessCopyTool,
    ProposeProcessUpdateTool,
    ProposeRuleUpdateTool,
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
        ListProcessesTool(),
        GetProcessTool(),
        SearchProcessCodeTool(),
        DiffProcessTool(),
        ListCubeViewsTool(),
        ListDimensionSubsetsTool(),
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
        ListChoresTool(),
        GetChoreTool(),
        GetCubeDependenciesTool(),
        GetDimensionDependentsTool(),
        GetObjectRelationshipsTool(),
        FindDependentsTool(),
        FindDependenciesTool(),
        DependencyPathTool(),
        FindUnusedObjectsTool(),
        ProposeRuleUpdateTool(),
        ProposeProcessUpdateTool(),
        ProposeProcessCopyTool(),
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
