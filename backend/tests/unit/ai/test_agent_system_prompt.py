"""An agent is never told it has no TM1 server.

The plain-chat instructions say "No TM1 server is connected in this mode".
They were also given to every specialist agent, after its own instructions
and the connection the user chose, and the model often obeyed them: it
refused its tools and told the user to connect a server they had connected.
Found by the live accuracy run; 7 of 11 answers were refusals.
"""

from src.ai.agents.registry import get_agent
from src.ai.orchestrator import PLAIN_CHAT_SYSTEM_PROMPT, _base_system


def test_plain_chat_keeps_its_instructions():
    assert _base_system(None, None, False) == PLAIN_CHAT_SYSTEM_PROMPT


def test_an_agent_does_not_get_the_no_server_instructions():
    assert _base_system(None, get_agent("developer"), False) is None


def test_asking_for_tools_without_an_agent_does_not_either():
    assert _base_system(None, None, True) is None


def test_a_callers_own_system_text_is_kept():
    assert _base_system("excerpts", get_agent("developer"), True) == "excerpts"
