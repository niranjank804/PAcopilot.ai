from pathlib import Path

import yaml

from src.ai.agents.base import AgentPersona

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_persona(path: Path) -> AgentPersona:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    return AgentPersona(
        name=data["name"],
        description=data["description"],
        system_prompt=data["system_prompt"],
        tool_names=data.get("tool_names"),
        max_tool_rounds=data.get("max_tool_rounds"),
        safety_notes=data.get("safety_notes"),
    )


def _load_all_personas(directory: Path = PROMPTS_DIR) -> dict[str, AgentPersona]:
    personas: dict[str, AgentPersona] = {}

    for path in sorted(directory.glob("*.yaml")):
        persona = _load_persona(path)

        if persona.name in personas:
            raise ValueError(
                f"Duplicate persona name '{persona.name}' — {path} conflicts "
                "with an earlier prompt file."
            )

        personas[persona.name] = persona

    return personas


# Personas are data now, not code — add a specialist by dropping a new YAML
# file in src/ai/prompts/, no Python change needed. Loaded once at import
# time; a malformed or duplicate-named file fails app startup immediately
# rather than silently, matching this codebase's fail-fast conventions.
AGENTS: dict[str, AgentPersona] = _load_all_personas()


def get_agent(name: str) -> AgentPersona | None:
    return AGENTS.get(name)


def list_agents() -> list[AgentPersona]:
    return list(AGENTS.values())
