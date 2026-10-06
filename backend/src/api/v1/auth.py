from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_active_user
from src.api.dependencies.rate_limit import auth_throttle
from src.database.session import get_db
from src.schemas.auth import (
    ForgotPasswordRequest,
    GoogleLoginRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from src.schemas.response import ApiResponse
from src.core.exceptions import AppException
from src.repositories.user_role_repository import user_role_repository
from src.services.auth_service import auth_service
from src.services.sign_in_service import sign_in_service

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=201,
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("register", "AUTH_REGISTER_PER_WINDOW")),
):
    user = await auth_service.register(
        db,
        request,
    )

    return ApiResponse(success=True, data=user)


@router.post(
    "/login",
    response_model=ApiResponse[TokenResponse],
)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("login", "AUTH_LOGIN_ATTEMPTS_PER_WINDOW")),
):
    try:
        token = await auth_service.login(
            db,
            request,
        )
    except AppException as error:
        await sign_in_service.record(
            db, http_request, method="password", success=False,
            identifier=request.username, reason=str(error),
        )
        # Committed before re-raising: the request rolls back on an
        # exception, and a failed attempt is exactly what must be kept.
        await db.commit()
        raise

    await sign_in_service.record(
        db, http_request, method="password", success=True,
        identifier=request.username, access_token=token.access_token,
    )

    return ApiResponse(success=True, data=token)


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenResponse],
)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("refresh", "AUTH_REFRESH_PER_WINDOW")),
):
    token = await auth_service.refresh(
        db,
        request,
    )

    # A refresh happens about every half hour of use, so it marks the
    # person as active without a write on every request.
    await sign_in_service.seen(db, token.access_token)

    return ApiResponse(success=True, data=token)


@router.post(
    "/google",
    response_model=ApiResponse[TokenResponse],
)
async def google_login(
    request: GoogleLoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("google_login", "AUTH_LOGIN_ATTEMPTS_PER_WINDOW")),
):
    try:
        token = await auth_service.google_login(db, request.id_token)
    except AppException as error:
        await sign_in_service.record(
            db, http_request, method="google", success=False, reason=str(error),
        )
        await db.commit()
        raise

    await sign_in_service.record(
        db, http_request, method="google", success=True, access_token=token.access_token,
    )

    return ApiResponse(success=True, data=token)


@router.post(
    "/forgot-password",
    response_model=ApiResponse[None],
)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("forgot_password", "AUTH_PASSWORD_RESET_PER_WINDOW")),
):
    await auth_service.request_password_reset(db, request.email)

    # Always the same response whether or not the email exists — see the
    # service method's own comment on why.
    return ApiResponse(success=True, data=None)


@router.post(
    "/reset-password",
    response_model=ApiResponse[None],
)
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _throttle: None = Depends(auth_throttle("reset_password", "AUTH_PASSWORD_RESET_PER_WINDOW")),
):
    await auth_service.reset_password(db, request.token, request.new_password)

    return ApiResponse(success=True, data=None)


@router.post(
    "/logout",
    response_model=ApiResponse[None],
)
async def logout(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_active_user),
):
    """End this session by revoking its refresh token."""

    await auth_service.logout(db, current_user.id, request.refresh_token)

    return ApiResponse(success=True, data=None)


@router.post(
    "/logout-all",
    response_model=ApiResponse[None],
)
async def logout_all(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_active_user),
):
    """End every session for this user, on every device."""

    await auth_service.logout_all(db, current_user.id)

    return ApiResponse(success=True, data=None)


@router.get(
    "/me",
    response_model=ApiResponse[UserResponse],
)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_active_user),
):
    # Role names, so the app can show what only some roles may open (the
    # platform view is the Super Admin's) without a request of its own.
    roles = await user_role_repository.role_names_by_user(db, [current_user.id])
    return ApiResponse(
        success=True,
        data=current_user.model_copy(update={"roles": roles.get(current_user.id, [])}),
    )