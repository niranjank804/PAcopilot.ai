from decimal import Decimal

from src.ai.schemas import Usage

# USD per 1M tokens: (input, output). Standard published rates.
#
# Every model this deployment can select must appear here. A model that is
# missing does not fail — it silently falls through to DEFAULT_PRICING,
# which produces a plausible-looking but wrong number in the usage ledger
# and in every per-organization cost total derived from it. The unit test
# asserting AI_DEFAULT_MODEL is a key of this dict exists to stop that
# pairing drifting apart again.
#
# claude-sonnet-5's introductory $2.00 / $10.00 rate ended 2026-08-31, so
# the standard rate below is now the rate actually billed.
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-7": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    # Priced above the Opus tier — the one model where falling through to
    # DEFAULT_PRICING would under-bill by half rather than round slightly.
    "claude-fable-5": (Decimal("10.00"), Decimal("50.00")),
}

# Opus-tier rates. Chosen as the default because under-estimating cost is
# worse than over-estimating it: a low guess quietly overspends a budget,
# a high guess only makes the ledger conservative.
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
