import inspect

import pytest

from src.ai.agents.registry import _load_all_personas, get_agent, list_agents
from src.ai.tools.registry import TOOLS


def test_get_agent_returns_known_persona():
    persona = get_agent("developer")

    assert persona is not None
    assert persona.name == "developer"
    assert persona.system_prompt


def test_get_agent_returns_none_for_unknown_name():
    assert get_agent("nonexistent") is None


def test_list_agents_returns_all_personas():
    names = {persona.name for persona in list_agents()}

    assert names == {
        "developer",
        "performance",
        "administrator",
        "architect",
        "documentation",
        "reviewer",
        "ti",
        "analyst",
        "troubleshooter",
    }


def test_every_persona_has_safety_notes():
    for persona in list_agents():
        assert persona.safety_notes, f"{persona.name} should have safety notes"


def test_every_persona_tool_name_exists_in_the_tool_registry():
    for persona in list_agents():
        assert persona.tool_names, f"{persona.name} should have a curated tool list"

        for tool_name in persona.tool_names:
            assert tool_name in TOOLS, (
                f"{persona.name} references unknown tool '{tool_name}'"
            )


def test_security_groups_are_never_exposed_as_ai_tools():
    # TM1 security metadata is API-only by explicit decision (narrower
    # tm1.security.read permission, no LLM access) — this guards against a
    # future round accidentally wiring it into the tool registry.
    for tool_name in TOOLS:
        assert "security" not in tool_name
        assert "group" not in tool_name


def test_no_ai_tool_can_execute_or_roll_back_a_change():
    # AI agents may only DRAFT changes (propose_rule_update /
    # propose_process_update) — a human holding tm1.deploy always reviews
    # and executes/rolls back via the existing Deployments pipeline. This
    # guards against a future round accidentally wiring real execution into
    # the AI's own tool-calling loop, whether directly or by name collision.
    for tool_name, tool in TOOLS.items():
        assert "execute_change" not in tool_name
        assert "rollback" not in tool_name

        source = inspect.getsource(type(tool).execute)
        assert "execute_change" not in source
        assert "rollback_change" not in source


def test_load_all_personas_parses_yaml_fields_correctly(tmp_path):
    (tmp_path / "sample.yaml").write_text(
        "name: sample\n"
        "description: A sample persona.\n"
        "system_prompt: You are a sample agent.\n"
        "tool_names:\n"
        "  - list_cubes\n"
        "max_tool_rounds: 3\n"
        "safety_notes:\n"
        "  - Be careful.\n",
        encoding="utf-8",
    )

    personas = _load_all_personas(tmp_path)

    assert set(personas) == {"sample"}
    persona = personas["sample"]
    assert persona.description == "A sample persona."
    assert persona.system_prompt == "You are a sample agent."
    assert persona.tool_names == ["list_cubes"]
    assert persona.max_tool_rounds == 3
    assert persona.safety_notes == ["Be careful."]


def test_load_all_personas_rejects_duplicate_names(tmp_path):
    for filename in ("a.yaml", "b.yaml"):
        (tmp_path / filename).write_text(
            "name: dup\n"
            "description: d\n"
            "system_prompt: p\n",
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="Duplicate persona name"):
        _load_all_personas(tmp_path)
