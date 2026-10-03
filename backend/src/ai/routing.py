"""Which model answers a turn, and what happens if it cannot.

Three tiers, all Anthropic (the owner's choice: TM1 data goes to one AI
company, and every tool is tested on these models):

    FAST      claude-haiku-4-5   plain questions, documentation
    BALANCED  claude-sonnet-5    TI development, troubleshooting, analysis
    BEST      claude-opus-5      architecture, review, anything on PROD

A person can pick a tier, or AUTO, which applies the fixed rules in
`auto_tier` — no model call, no guessing, the same message always routes
the same way, and the reason is shown with the answer. AUTO never sends a
tool-using specialist below BALANCED: cost is saved where capability is not
needed, never by trading it away.

A tier whose model this deployment does not allow (AI_ALLOWED_MODELS) moves
up to the next allowed one, and says so.

If the chosen model is overloaded or unreachable before it has said
anything, the turn is retried once on the neighbouring tier; the answer and
the usage ledger record that it fell back.
"""

import re
from dataclasses import dataclass

from src.ai.exceptions import AIProviderAuthenticationError, AIProviderError, AIProviderRateLimitError
from src.core.config import settings
from src.core.exceptions import ValidationException

TIER_MODELS = {
    "fast": "claude-haiku-4-5",
    "balanced": "claude-sonnet-5",
    "best": "claude-opus-5",
}
TIERS = tuple(TIER_MODELS)
CHOICES = ("auto", *TIERS)

# The neighbouring tier to retry on. Never down to FAST: a fallback must not
# answer a specialist's question with a weaker model than it asked for.
FALLBACK = {"best": "balanced", "balanced": "best", "fast": "balanced"}

# Agents that work through TM1 tools in a loop. AUTO keeps them at BALANCED
# or above.
TOOL_AGENTS = {"developer", "ti", "troubleshooter", "administrator", "analyst", "performance"}
BEST_AGENTS = {"architect", "reviewer"}
FAST_AGENTS = {"documentation"}

# Attachment text beyond this is a large document to reason over.
LARGE_ATTACHMENT_CHARS = 40_000


@dataclass(frozen=True)
class RouteDecision:
    model: str
    tier: str | None  # None for an explicitly named model
    requested: str  # what the person asked for: auto / a tier / a model id
    reason: str
    fallback_model: str | None

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "tier": self.tier,
            "requested": self.requested,
            "reason": self.reason,
        }


def auto_tier(
    *, agent: str | None, environment: str | None, attachment_chars: int = 0
) -> tuple[str, str]:
    """AUTO's rules, in order. Returns (tier, reason)."""

    if environment == "prod":
        return "best", "the selected TM1 server is production"
    if agent in BEST_AGENTS:
        return "best", f"the {agent} agent needs the most careful reasoning"
    if attachment_chars > LARGE_ATTACHMENT_CHARS:
        return "balanced", "a large attachment to reason over"
    if agent in TOOL_AGENTS:
        return "balanced", f"the {agent} agent works through TM1 tools"
    if agent in FAST_AGENTS:
        return "fast", "documentation"
    if agent is None:
        return "fast", "a plain question with no specialist agent"
    return "balanced", f"the {agent} agent"


def _allowed(tier: str) -> str | None:
    """The model for `tier`, or the next tier up that this deployment allows."""

    order = list(TIERS)
    for candidate in order[order.index(tier):]:
        if TIER_MODELS[candidate] in settings.AI_ALLOWED_MODELS:
            return candidate
    return None


def decide(
    requested: str | None,
    *,
    agent: str | None,
    environment: str | None,
    attachment_chars: int = 0,
) -> RouteDecision:
    """The model for this turn."""

    choice = (requested or "auto").strip()

    # A model named outright (older clients, or an operator testing one).
    if choice not in CHOICES:
        if choice not in settings.AI_ALLOWED_MODELS:
            raise ValidationException(
                f"Model not available: {choice}. Choose auto, fast, balanced or best."
            )
        return RouteDecision(choice, None, choice, "chosen by name", None)

    if choice == "auto":
        tier, reason = auto_tier(agent=agent, environment=environment, attachment_chars=attachment_chars)
        reason = f"AUTO: {reason}"
    else:
        tier, reason = choice, f"{choice.upper()} chosen"

    allowed = _allowed(tier)
    if allowed is None:
        # Nothing at or above the tier is allowed: use the deployment default.
        return RouteDecision(settings.AI_DEFAULT_MODEL, None, choice, reason + "; deployment default model", None)
    if allowed != tier:
        reason += f"; {tier.upper()} is not enabled here, so {allowed.upper()}"

    fallback_tier = _allowed(FALLBACK[allowed]) if FALLBACK[allowed] else None
    fallback = TIER_MODELS[fallback_tier] if fallback_tier and fallback_tier != allowed else None

    return RouteDecision(TIER_MODELS[allowed], allowed, choice, reason, fallback)


_RETRYABLE = re.compile(r"error code:\s*(5\d\d)|overloaded|connection error|timed out|timeout", re.IGNORECASE)


def is_retryable(exc: Exception) -> bool:
    """Overloaded, a server error, a dropped connection or a rate limit:
    another model may answer. A bad request or a bad key would fail the
    same way on any model."""

    if isinstance(exc, AIProviderAuthenticationError):
        return False
    if isinstance(exc, AIProviderRateLimitError):
        return True
    return isinstance(exc, AIProviderError) and bool(_RETRYABLE.search(str(exc)))


class FallbackProvider:
    """A provider for one turn that retries once on the fallback model when
    the first fails before saying anything, and then stays on it for the
    rest of the turn, so one answer never mixes two models mid-thought."""

    def __init__(self, inner, primary_model: str, fallback_model: str | None):
        self._inner = inner
        self._primary = primary_model
        self._fallback = fallback_model
        self.fell_back = False

    @property
    def model_used(self) -> str:
        return self._fallback if self.fell_back else self._primary

    def _switch(self, request):
        return request.model_copy(update={"model": self._fallback}) if self.fell_back else request

    async def chat(self, request):
        try:
            return await self._inner.chat(self._switch(request))
        except Exception as exc:
            if self.fell_back or not self._fallback or not is_retryable(exc):
                raise
            self.fell_back = True
            return await self._inner.chat(self._switch(request))

    async def stream_chat(self, request):
        started = False
        try:
            async for event in self._inner.stream_chat(self._switch(request)):
                started = True
                yield event
            return
        except Exception as exc:
            if started or self.fell_back or not self._fallback or not is_retryable(exc):
                raise
            self.fell_back = True

        async for event in self._inner.stream_chat(self._switch(request)):
            yield event
