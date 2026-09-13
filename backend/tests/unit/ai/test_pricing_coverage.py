"""Pricing table must cover every model this deployment can select.

A model missing from PRICING does not raise — estimate_cost() falls back
to DEFAULT_PRICING and returns a plausible-looking number. That number
feeds AIUsage rows, per-organization spend totals and the monthly token
cap, so a silent fallback corrupts billing data rather than failing
loudly. These tests make the drift visible at CI time instead.

The concrete case that prompted them: AI_DEFAULT_MODEL was moved to
claude-opus-5 while PRICING still listed only claude-opus-4-8, so every
request priced via the fallback. It happened to carry the same rate, so
nothing looked wrong.
"""

from decimal import Decimal

from src.ai.pricing import DEFAULT_PRICING, PRICING, estimate_cost
from src.ai.schemas import Usage
from src.core.config import settings


def test_default_model_is_priced_explicitly():
    assert settings.AI_DEFAULT_MODEL in PRICING, (
        f"AI_DEFAULT_MODEL {settings.AI_DEFAULT_MODEL!r} is not in PRICING, "
        "so every request silently prices against DEFAULT_PRICING."
    )


def test_fable_is_priced_above_the_fallback():
    """The one model where the fallback would under-bill, not round."""

    assert PRICING["claude-fable-5"][0] > DEFAULT_PRICING[0]
    assert PRICING["claude-fable-5"][1] > DEFAULT_PRICING[1]


def test_every_rate_is_positive():
    for model, (input_rate, output_rate) in PRICING.items():
        assert input_rate > 0, model
        assert output_rate > 0, model
        # Output is dearer than input on every published Anthropic rate;
        # a table entry where it is not is a transposed tuple.
        assert output_rate > input_rate, model


def test_estimate_cost_uses_the_table_not_the_fallback():
    """A priced model must not coincidentally match the fallback."""

    usage = Usage(input_tokens=1_000_000, output_tokens=0)

    # Haiku is the cheapest entry, so a fallback would be conspicuous.
    assert estimate_cost("claude-haiku-4-5", usage) == Decimal("1.00")


def test_unknown_model_falls_back_rather_than_raising():
    """Fallback is deliberate: an unknown model must not break a request
    mid-conversation. It is only the *silent* part that is the problem,
    which the default-model test above now catches."""

    usage = Usage(input_tokens=1_000_000, output_tokens=0)

    assert estimate_cost("some-unreleased-model", usage) == DEFAULT_PRICING[0]
