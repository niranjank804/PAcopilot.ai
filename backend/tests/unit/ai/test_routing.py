"""Model routing (phase 9): which tier answers, and the one-step fallback."""

import pytest

from src.ai.exceptions import AIProviderAuthenticationError, AIProviderError, AIProviderRateLimitError
from src.ai.routing import FallbackProvider, auto_tier, decide, is_retryable
from src.ai.schemas import ChatMessage, ChatRequest
from src.core.config import settings
from src.core.exceptions import ValidationException


@pytest.mark.parametrize(
    ("agent", "environment", "chars", "tier"),
    [
        (None, None, 0, "fast"),
        ("documentation", None, 0, "fast"),
        ("developer", None, 0, "balanced"),
        ("troubleshooter", "dev", 0, "balanced"),
        ("architect", None, 0, "best"),
        ("reviewer", None, 0, "best"),
        # Production raises the tier whatever the agent.
        (None, "prod", 0, "best"),
        ("developer", "prod", 0, "best"),
        # A big document is not a FAST job.
        (None, None, 100_000, "balanced"),
    ],
)
def test_auto_follows_fixed_rules(agent, environment, chars, tier):
    assert auto_tier(agent=agent, environment=environment, attachment_chars=chars)[0] == tier


def test_auto_never_sends_a_tool_agent_below_balanced():
    for agent in ("developer", "ti", "troubleshooter", "administrator", "analyst", "performance"):
        assert auto_tier(agent=agent, environment=None)[0] in ("balanced", "best")


def test_a_decision_names_the_model_and_why():
    decision = decide(None, agent="developer", environment="dev")

    assert decision.model == "claude-sonnet-5" and decision.tier == "balanced"
    assert decision.requested == "auto"
    assert decision.reason.startswith("AUTO:") and "developer" in decision.reason
    assert decision.fallback_model == "claude-opus-5"


def test_a_chosen_tier_overrides_auto():
    assert decide("best", agent=None, environment=None).model == "claude-opus-5"
    assert decide("fast", agent="architect", environment=None).model == "claude-haiku-4-5"


def test_a_model_named_outright_must_be_allowed():
    assert decide("claude-sonnet-5", agent=None, environment=None).tier is None
    with pytest.raises(ValidationException):
        decide("gpt-5", agent=None, environment=None)


def test_a_tier_this_deployment_does_not_allow_moves_up_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "AI_ALLOWED_MODELS", ["claude-opus-5", "claude-sonnet-5"])

    decision = decide(None, agent=None, environment=None)

    assert decision.model == "claude-sonnet-5"
    assert "FAST is not enabled here" in decision.reason


def test_the_fallback_is_never_cheaper_than_balanced():
    assert decide("fast", agent=None, environment=None).fallback_model == "claude-sonnet-5"
    assert decide("best", agent=None, environment=None).fallback_model == "claude-sonnet-5"


def test_only_errors_another_model_could_avoid_are_retried():
    assert is_retryable(AIProviderError("Error code: 529 - overloaded_error"))
    assert is_retryable(AIProviderError("Error code: 503 - service unavailable"))
    assert is_retryable(AIProviderError("Connection error."))
    assert is_retryable(AIProviderRateLimitError("rate limited"))
    assert not is_retryable(AIProviderError("Error code: 400 - prompt is too long"))
    assert not is_retryable(AIProviderAuthenticationError("bad key"))


class _Inner:
    def __init__(self, fail_on: set[str], after_events: int = 0):
        self.fail_on = fail_on
        self.after_events = after_events
        self.models: list[str] = []

    async def chat(self, request):
        self.models.append(request.model)
        if request.model in self.fail_on:
            raise AIProviderError("Error code: 529 - overloaded_error")
        return f"answered by {request.model}"

    async def stream_chat(self, request):
        self.models.append(request.model)
        for i in range(2):
            if request.model in self.fail_on and i == self.after_events:
                raise AIProviderError("Error code: 529 - overloaded_error")
            yield f"{request.model}:{i}"


def _request(model):
    return ChatRequest(messages=[ChatMessage(role="user", content="hi")], model=model)


@pytest.mark.asyncio
async def test_an_overloaded_model_falls_back_once_and_stays_there():
    inner = _Inner(fail_on={"claude-opus-5"})
    provider = FallbackProvider(inner, "claude-opus-5", "claude-sonnet-5")

    assert await provider.chat(_request("claude-opus-5")) == "answered by claude-sonnet-5"
    assert provider.fell_back and provider.model_used == "claude-sonnet-5"
    # The next round of the same turn goes straight to the fallback.
    await provider.chat(_request("claude-opus-5"))
    assert inner.models == ["claude-opus-5", "claude-sonnet-5", "claude-sonnet-5"]


@pytest.mark.asyncio
async def test_a_stream_falls_back_only_before_its_first_word():
    early = FallbackProvider(_Inner(fail_on={"claude-opus-5"}), "claude-opus-5", "claude-sonnet-5")
    assert [e async for e in early.stream_chat(_request("claude-opus-5"))] == [
        "claude-sonnet-5:0", "claude-sonnet-5:1"
    ]

    late = FallbackProvider(_Inner(fail_on={"claude-opus-5"}, after_events=1), "claude-opus-5", "claude-sonnet-5")
    with pytest.raises(AIProviderError):
        # Half an answer from one model is never finished by another.
        [e async for e in late.stream_chat(_request("claude-opus-5"))]


@pytest.mark.asyncio
async def test_without_a_fallback_the_error_stands():
    provider = FallbackProvider(_Inner(fail_on={"claude-sonnet-5"}), "claude-sonnet-5", None)

    with pytest.raises(AIProviderError):
        await provider.chat(_request("claude-sonnet-5"))
