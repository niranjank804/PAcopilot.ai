"""The two rules src/ai/tools/classification.py promises, enforced.

1. Every registered tool is classified: a tool the UI cannot describe
   honestly (what it reads, whether it changes anything) fails the build.
2. No AI tool changes TM1. Only `propose_*` tools are above VALIDATE, and
   those only draft a change a person approves.
"""

import inspect

from src.ai.tools.classification import CLASSIFICATION, ToolAccess
from src.ai.tools.registry import list_tools


def test_every_registered_tool_is_classified_and_nothing_else_is():
    registered = {tool.name for tool in list_tools()}

    assert registered - CLASSIFICATION.keys() == set(), "unclassified tools"
    assert CLASSIFICATION.keys() - registered == set(), "classified tools that do not exist"


def test_only_propose_tools_write_or_execute_and_they_ask_first():
    for name, classification in CLASSIFICATION.items():
        drafts = name.startswith("propose_")
        acts = classification.access in (ToolAccess.WRITE, ToolAccess.EXECUTE)

        assert drafts == acts, name
        assert classification.requires_confirmation == acts, name
        assert classification.access is not ToolAccess.ADMIN, name


def test_target_keys_are_real_inputs_of_the_tool():
    # The UI shows these as "acts on"; a key the tool does not take would
    # show nothing, or the wrong thing.
    for tool in list_tools():
        properties = tool.input_schema.get("properties", {})
        for key in CLASSIFICATION[tool.name].target_keys:
            assert key in properties, f"{tool.name}: {key}"


def test_no_tool_source_calls_tm1_writes_directly():
    # Belt and braces for rule 2: a tool's module never reaches TM1py's
    # mutating calls itself; it goes through change_service drafts.
    forbidden = (".update_or_create(", ".delete(", ".execute_with_return(", ".update_or_create_rules(")
    for tool in list_tools():
        source = inspect.getsource(inspect.getmodule(type(tool)))
        for call in forbidden:
            assert call not in source, f"{type(tool).__module__} calls {call}"
