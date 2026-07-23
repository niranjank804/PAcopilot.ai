class AgentPersona:

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tool_names: list[str] | None = None,
        max_tool_rounds: int | None = None,
        safety_notes: list[str] | None = None,
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tool_names = tool_names
        self.max_tool_rounds = max_tool_rounds
        self.safety_notes = safety_notes
