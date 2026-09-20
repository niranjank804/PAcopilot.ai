from fastapi import Depends, Request

from src.api.dependencies.auth import get_current_active_user
from src.core import rate_limit
from src.core.config import settings
from src.schemas.auth import UserResponse


def rate_limited(scope: str):
    """Guard a route with the per-user and per-organization windows.

    `scope` separates the budgets: the AI scope is much tighter than the
    general one, and spending one must not consume the other. Compose
    alongside require_permission — FastAPI resolves the shared
    get_current_active_user dependency once per request.
    """

    user_setting, organization_setting = _LIMIT_SETTINGS.get(
        scope, _LIMIT_SETTINGS["general"]
    )

    async def checker(
        current_user: UserResponse = Depends(get_current_active_user),
    ) -> UserResponse:

        # Resolved per request rather than captured, so a test (or an
        # operator) can change a limit without rebuilding the app.
        rate_limit.enforce(
            scope=scope,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            user_limit=getattr(settings, user_setting),
            organization_limit=getattr(settings, organization_setting),
        )

        return current_user

    return checker


# Scope -> (per-user setting, per-organization setting).
_LIMIT_SETTINGS = {
    "general": ("RATE_LIMIT_USER_PER_WINDOW", "RATE_LIMIT_ORG_PER_WINDOW"),
    "ai": ("RATE_LIMIT_AI_USER_PER_WINDOW", "RATE_LIMIT_AI_ORG_PER_WINDOW"),
    "heavy": ("RATE_LIMIT_HEAVY_USER_PER_WINDOW", "RATE_LIMIT_HEAVY_ORG_PER_WINDOW"),
}

ai_rate_limited = rate_limited("ai")
general_rate_limited = rate_limited("general")
# Parsing, embedding, corpus analysis, whole-model extraction.
heavy_rate_limited = rate_limited("heavy")


def auth_throttle(scope: str, limit_setting: str):
    """IP-keyed throttle for an endpoint reachable without a token.

    `limit_setting` names the attribute on `settings` rather than reading
    its value here, so the limit is resolved per request and a test can
    monkeypatch it.
    """

    async def checker(request: Request) -> None:
        rate_limit.enforce_ip(
            scope=f"auth:{scope}",
            # Not request.client.host: behind a proxy that is the
            # proxy's address, which collapses every client into one
            # bucket and turns a per-attacker limit into a global cap.
            client_ip=rate_limit.client_ip_of(request),
            limit=getattr(settings, limit_setting),
        )

    return checker
