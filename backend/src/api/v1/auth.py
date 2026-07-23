from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_active_user
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
from src.services.auth_service import auth_service

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
    db: AsyncSession = Depends(get_db),
):
    token = await auth_service.login(
        db,
        request,
    )

    return ApiResponse(success=True, data=token)


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenResponse],
)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    token = await auth_service.refresh(
        db,
        request,
    )

    return ApiResponse(success=True, data=token)


@router.post(
    "/google",
    response_model=ApiResponse[TokenResponse],
)
async def google_login(
    request: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    token = await auth_service.google_login(db, request.id_token)

    return ApiResponse(success=True, data=token)


@router.post(
    "/forgot-password",
    response_model=ApiResponse[None],
)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
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
):
    await auth_service.reset_password(db, request.token, request.new_password)

    return ApiResponse(success=True, data=None)


@router.get(
    "/me",
    response_model=ApiResponse[UserResponse],
)
async def get_me(
    current_user: UserResponse = Depends(get_current_active_user),
):
    return ApiResponse(success=True, data=current_user)