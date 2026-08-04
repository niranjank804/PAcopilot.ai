import pytest

from src.billing import (
    DEFAULT_PLAN,
    PLANS,
    get_plan,
    list_plans,
    monthly_token_limit_for,
)


class TestCatalog:

    def test_expected_plans_exist(self):
        assert {"trial", "professional", "enterprise", "internal"} <= set(PLANS)

    def test_public_listing_excludes_internal(self):
        keys = [p.key for p in list_plans()]
        assert "internal" not in keys
        assert keys == ["trial", "professional", "enterprise"]

    def test_private_listing_includes_internal(self):
        assert "internal" in [p.key for p in list_plans(include_private=True)]

    def test_limits_increase_with_tier(self):
        trial = get_plan("trial")
        professional = get_plan("professional")

        assert trial.monthly_token_limit < professional.monthly_token_limit
        assert trial.max_users < professional.max_users
        assert trial.max_connections < professional.max_connections

    def test_enterprise_is_unlimited(self):
        enterprise = get_plan("enterprise")

        assert enterprise.monthly_token_limit is None
        assert enterprise.max_users is None
        assert enterprise.max_connections is None

    def test_serialisable(self):
        payload = get_plan("trial").as_dict()

        assert payload["key"] == "trial"
        assert isinstance(payload["features"], list)
        assert payload["features"]

    def test_plans_are_immutable(self):
        with pytest.raises(Exception):
            get_plan("trial").monthly_token_limit = 1


class TestGetPlan:
    """An organization must never lose access because its stored plan key is
    not in the current catalog, so resolution always falls back."""

    @pytest.mark.parametrize("key", [None, "", "  ", "nonexistent", "LEGACY_GOLD"])
    def test_unknown_falls_back_to_default(self, key):
        assert get_plan(key) is DEFAULT_PLAN

    @pytest.mark.parametrize("key", ["TRIAL", "Trial", "  professional  "])
    def test_case_and_whitespace_tolerant(self, key):
        assert get_plan(key).key == key.strip().lower()


class TestTokenLimit:
    """The stricter of the plan limit and the deployment setting wins."""

    def test_plan_limit_applies_when_no_deployment_limit(self):
        assert monthly_token_limit_for("trial") == 2_000_000

    def test_deployment_limit_binds_metered_plans(self):
        # AI_MONTHLY_TOKEN_LIMIT is an operator safety backstop. Someone who
        # sets it during a runaway-spend incident expects it to bind
        # everyone, so a plan must not be able to exceed it.
        assert monthly_token_limit_for("trial", deployment_limit=99) == 99

    def test_deployment_limit_binds_unlimited_plans(self):
        assert monthly_token_limit_for("enterprise", deployment_limit=99) == 99

    def test_plan_limit_binds_when_stricter(self):
        assert monthly_token_limit_for(
            "trial", deployment_limit=50_000_000
        ) == 2_000_000

    def test_unlimited_plan_with_no_deployment_limit_is_unlimited(self):
        assert monthly_token_limit_for("enterprise") is None

    def test_unknown_plan_uses_default_limit(self):
        assert monthly_token_limit_for("nope") == DEFAULT_PLAN.monthly_token_limit

    def test_internal_plan_is_unmetered(self):
        assert monthly_token_limit_for("internal") is None
