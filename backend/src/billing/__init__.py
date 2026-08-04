"""Plan catalog and entitlements.

Plans are defined in code, not rows. The catalog changes with a deploy, and
pinning it to the codebase means an organization's entitlements can be
reasoned about from the source rather than reconstructed from database
state. Only the *assignment* (which plan an organization is on) is stored,
as `Organization.plan`.

Limits are advisory ceilings, not billing. Nothing here charges anyone or
talks to a payment provider — it exists so usage can be metered against a
plan and so the product can state what each tier includes.
"""

from src.billing.plans import (
    DEFAULT_PLAN,
    PLANS,
    Plan,
    get_plan,
    list_plans,
    monthly_token_limit_for,
)

__all__ = [
    "DEFAULT_PLAN",
    "PLANS",
    "Plan",
    "get_plan",
    "list_plans",
    "monthly_token_limit_for",
]
