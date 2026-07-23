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


def estimate_cost(model: str, usage: Usage) -> Decimal:
    input_price, output_price = PRICING.get(model, DEFAULT_PRICING)

    million = Decimal("1000000")

    input_cost = (Decimal(usage.input_tokens) / million) * input_price
    output_cost = (Decimal(usage.output_tokens) / million) * output_price

    return input_cost + output_cost
