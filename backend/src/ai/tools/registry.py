from src.ai.tools.base import Tool
from src.ai.tools.knowledge import SearchKnowledgeBaseTool
from src.ai.tools.tm1.analysis import (
    DependencyPathTool,
    FindDependenciesTool,
    FindDependentsTool,
    FindUnusedObjectsTool,
)
from src.ai.tools.tm1.cells import ExecuteMDXTool
from src.ai.tools.tm1.changes import (
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
from src.ai.tools.tm1.processes import GetProcessTool, ListProcessesTool
from src.ai.tools.tm1.standards import GetCodingStandardsTool

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
        ListProcessesTool(),
        GetProcessTool(),
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
