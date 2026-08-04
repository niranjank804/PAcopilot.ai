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

    is_ai = scope == "ai"

    async def checker(
        current_user: UserResponse = Depends(get_current_active_user),
    ) -> UserResponse:

        rate_limit.enforce(
            scope=scope,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            user_limit=(
                settings.RATE_LIMIT_AI_USER_PER_WINDOW
                if is_ai
                else settings.RATE_LIMIT_USER_PER_WINDOW
            ),
            organization_limit=(
                settings.RATE_LIMIT_AI_ORG_PER_WINDOW
                if is_ai
                else settings.RATE_LIMIT_ORG_PER_WINDOW
            ),
        )

        return current_user

    return checker


ai_rate_limited = rate_limited("ai")
general_rate_limited = rate_limited("general")


def auth_throttle(scope: str, limit_setting: str):
    """IP-keyed throttle for an endpoint reachable without a token.

    `limit_setting` names the attribute on `settings` rather than reading
    its value here, so the limit is resolved per request and a test can
    monkeypatch it.
    """

    async def checker(request: Request) -> None:
        rate_limit.enforce_ip(
            scope=f"auth:{scope}",
            client_ip=request.client.host if request.client else None,
            limit=getattr(settings, limit_setting),
        )

    return checker
