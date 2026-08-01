from decimal import Decimal

from src.ai.schemas import Usage

# USD per 1M tokens: (input, output). Standard published rates.
# NOTE: claude-sonnet-5 has an introductory rate of $2.00 / $10.00 per 1M
# tokens through 2026-08-31; this table uses the standard post-intro rate
# to avoid a time-based pricing table, so cost estimates are slightly high
# for claude-sonnet-5 until that date.
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}

DEFAULT_PRICING = (Decimal("5.00"), Decimal("25.00"))

# Cached input is billed against the same per-model input rate, scaled:
# writing an entry costs a premium over an ordinary input token, reading
# one costs a fraction. With the 5-minute TTL a prefix pays for itself on
# its second use (1.25 + 0.1 < 2.0).
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
CACHE_READ_MULTIPLIER = Decimal("0.10")

_MILLION = Decimal("1000000")


def estimate_cost(model: str, usage: Usage) -> Decimal:
    input_price, output_price = PRICING.get(model, DEFAULT_PRICING)

    # input_tokens is the *uncached remainder* only — the cache counters
    # are not a subset of it. Summing all three gives the real prompt size.
    uncached = (Decimal(usage.input_tokens) / _MILLION) * input_price

    cache_write = (
        (Decimal(usage.cache_creation_input_tokens) / _MILLION)
        * input_price
        * CACHE_WRITE_MULTIPLIER
    )

    cache_read = (
        (Decimal(usage.cache_read_input_tokens) / _MILLION)
        * input_price
        * CACHE_READ_MULTIPLIER
    )

    output = (Decimal(usage.output_tokens) / _MILLION) * output_price

    return uncached + cache_write + cache_read + output


def cost_without_cache(model: str, usage: Usage) -> Decimal:
    """What this request would have cost with caching switched off.

    Every cached token would otherwise have been an ordinary input token,
    so the counterfactual is the full prompt at the plain input rate.
    Subtracting estimate_cost from this is the realised saving.
    """

    input_price, output_price = PRICING.get(model, DEFAULT_PRICING)

    prompt_tokens = (
        usage.input_tokens
        + usage.cache_creation_input_tokens
        + usage.cache_read_input_tokens
    )

    return (Decimal(prompt_tokens) / _MILLION) * input_price + (
        Decimal(usage.output_tokens) / _MILLION
    ) * output_price
