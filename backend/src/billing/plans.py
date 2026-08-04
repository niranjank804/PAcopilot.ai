"""The plan catalog.

`monthly_token_limit` is the only limit enforced today (see
`AIOrchestrator._check_usage_quota`). `max_users` and `max_connections` are
published entitlements that nothing enforces yet — they are declared here so
the catalog and the pricing page tell the same story, and so enforcement can
be added later without changing the public shape.

A limit of None means unlimited.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:

    key: str
    name: str
    description: str
    monthly_token_limit: int | None
    max_users: int | None
    max_connections: int | None
    features: tuple[str, ...] = field(default_factory=tuple)
    # Presentation only. Priced plans are quoted rather than self-serve, so
    # this is a label ("Contact us"), never a number the app charges against.
    price_label: str = "Contact us"
    is_public: bool = True

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "monthly_token_limit": self.monthly_token_limit,
            "max_users": self.max_users,
            "max_connections": self.max_connections,
            "features": list(self.features),
            "price_label": self.price_label,
        }


_CORE_FEATURES = (
    "Grounded TI, rule and MDX generation",
    "Live compile validation of TurboIntegrator drafts",
    "Human-gated deployment with snapshot and rollback",
    "Metadata explorer and dependency graph",
    "Knowledge Base grounding in your own standards",
)

TRIAL = Plan(
    key="trial",
    name="Trial",
    description=(
        "Evaluate the full product against a single Planning Analytics "
        "connection."
    ),
    monthly_token_limit=2_000_000,
    max_users=5,
    max_connections=1,
    features=_CORE_FEATURES,
    price_label="Free",
)

PROFESSIONAL = Plan(
    key="professional",
    name="Professional",
    description=(
        "For a working TM1 team: more connections, more seats, and usage "
        "headroom for day-to-day development."
    ),
    monthly_token_limit=20_000_000,
    max_users=25,
    max_connections=5,
    features=_CORE_FEATURES
    + (
        "Multiple TM1 connections",
        "Full change history and audit trail",
        "Usage and cost reporting",
    ),
)

ENTERPRISE = Plan(
    key="enterprise",
    name="Enterprise",
    description=(
        "For organizations with their own security, identity and governance "
        "requirements."
    ),
    monthly_token_limit=None,
    max_users=None,
    max_connections=None,
    features=PROFESSIONAL.features
    + (
        "Unlimited seats and connections",
        "Dedicated infrastructure",
        "Security review support",
    ),
)

# Not offered publicly; the escape hatch for internal and demo organizations
# that must not be metered.
INTERNAL = Plan(
    key="internal",
    name="Internal",
    description="Unmetered. Not offered for sale.",
    monthly_token_limit=None,
    max_users=None,
    max_connections=None,
    features=ENTERPRISE.features,
    price_label="—",
    is_public=False,
)

PLANS: dict[str, Plan] = {
    plan.key: plan for plan in (TRIAL, PROFESSIONAL, ENTERPRISE, INTERNAL)
}

DEFAULT_PLAN = TRIAL


def get_plan(key: str | None) -> Plan:
    """Resolve a plan key. Unknown or missing keys fall back to the default
    rather than raising — an organization must never lose access because its
    plan column holds something the current catalog no longer defines."""

    if not key:
        return DEFAULT_PLAN

    return PLANS.get(str(key).strip().lower(), DEFAULT_PLAN)


def list_plans(include_private: bool = False) -> list[Plan]:
    """Catalog in presentation order."""

    ordered = (TRIAL, PROFESSIONAL, ENTERPRISE, INTERNAL)

    return [p for p in ordered if include_private or p.is_public]


def monthly_token_limit_for(
    plan_key: str | None,
    deployment_limit: int | None = None,
) -> int | None:
    """The token ceiling to enforce for an organization on `plan_key`.

    The stricter of the plan's own limit and the deployment-wide setting
    wins; None means unlimited on either side. Both directions matter:

      * The plan limit is the commercial ceiling — what the customer bought.
      * `deployment_limit` (AI_MONTHLY_TOKEN_LIMIT) is an operator safety
        backstop. Someone who sets it during a runaway-spend incident expects
        it to bind everyone, including paid and otherwise-unlimited plans, so
        it cannot be something a plan is allowed to override.
    """

    limits = [
        limit
        for limit in (get_plan(plan_key).monthly_token_limit, deployment_limit)
        if limit is not None
    ]

    return min(limits) if limits else None
