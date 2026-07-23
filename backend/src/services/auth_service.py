import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    AuthenticationException,
    ConflictException,
    NotFoundException,
    PermissionDeniedException,
)
from src.database.models.password_reset_token import PasswordResetToken
from src.database.models.user import User
from src.email.registry import get_email_provider
from src.repositories.organization_repository import organization_repository
from src.repositories.password_reset_token_repository import (
    password_reset_token_repository,
)
from src.repositories.user_repository import user_repository
from src.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from src.services.google_oauth import verify_google_id_token
from src.services.jwt_service import jwt_service
from src.services.password_service import password_service


def _hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _check_can_authenticate(user: User) -> None:
    """Shared gate for every path that issues tokens (login, refresh,
    Google sign-in) — registration_status is checked first since a
    pending/rejected account should never even reach the is_active check."""

    if user.registration_status == "pending":
        raise PermissionDeniedException(
            "Your account is pending administrator approval."
        )

    if user.registration_status == "rejected":
        raise PermissionDeniedException(
            "Your access request was not approved. Contact your "
            "administrator."
        )

    if not user.is_active:
        raise PermissionDeniedException("User account is inactive")


class AuthService:
    async def register(
        self,
        db: AsyncSession,
        request: RegisterRequest,
    ) -> UserResponse:

        organization = await organization_repository.get_by_code(
            db,
            request.organization_code,
        )

        if organization is None:
            raise NotFoundException(
                "No organization found with that code. Check it with your "
                "administrator."
            )

        existing_user = await user_repository.get_by_username(
            db,
            request.username,
        )

        if existing_user:
            raise ConflictException("Username already exists")

        existing_email = await user_repository.get_by_email(
            db,
            request.email,
        )

        if existing_email:
            raise ConflictException("Email already exists")

        # Every self-registration is a REQUEST, not an active account — an
        # Organization Admin must approve it (see user_service.approve_user)
        # before it can log in. is_active stays True so it's not confused
        # with an admin-disabled account; registration_status is the gate.
        user = User(
            organization_id=organization.id,
            username=request.username,
            email=request.email,
            password_hash=password_service.hash_password(
                request.password
            ),
            first_name=request.first_name,
            last_name=request.last_name,
            is_active=True,
            registration_status="pending",
        )

        user = await user_repository.create(db, user)

        return UserResponse.model_validate(user)

    async def login(
        self,
        db: AsyncSession,
        request: LoginRequest,
    ) -> TokenResponse:

        user = await user_repository.get_by_username(
            db,
            request.username,
        )

        if user is None:
            raise AuthenticationException("Invalid username or password")

        if not password_service.verify_password(
            request.password,
            user.password_hash,
        ):
            raise AuthenticationException("Invalid username or password")

        _check_can_authenticate(user)

        access_token = jwt_service.create_access_token(
            str(user.id)
        )

        refresh_token = jwt_service.create_refresh_token(
            str(user.id)
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def refresh(
        self,
        db: AsyncSession,
        request: RefreshRequest,
    ) -> TokenResponse:

        try:
            payload = jwt_service.decode_token(request.refresh_token)

            if payload.get("type") != "refresh":
                raise AuthenticationException("Invalid token type")

            user_id = uuid.UUID(payload["sub"])

        except (JWTError, ValueError, KeyError):
            raise AuthenticationException("Invalid or expired refresh token")

        user = await user_repository.get_by_id(db, user_id)

        if user is None:
            raise AuthenticationException("Invalid or expired refresh token")

        _check_can_authenticate(user)

        access_token = jwt_service.create_access_token(str(user.id))
        refresh_token = jwt_service.create_refresh_token(str(user.id))

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def request_password_reset(
        self,
        db: AsyncSession,
        email: str,
    ) -> None:

        user = await user_repository.get_by_email(db, email)

        # Deliberately a silent no-op for an unknown email or inactive
        # user, not an error — responding differently would let a caller
        # enumerate which emails have accounts.
        if user is None or not user.is_active:
            return

        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )

        await password_reset_token_repository.create(
            db,
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=expires_at,
            ),
        )

        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"

        await get_email_provider().send(
            to=user.email,
            subject="Reset your PA-Copilot password",
            body=(
                f"Hi {user.first_name},\n\n"
                "Someone requested a password reset for your PA-Copilot "
                "account. If this was you, reset it here (expires in "
                f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):\n\n"
                f"{reset_link}\n\n"
                "If you didn't request this, you can safely ignore this "
                "email — your password hasn't changed."
            ),
        )

    async def reset_password(
        self,
        db: AsyncSession,
        token: str,
        new_password: str,
    ) -> None:

        reset_token = await password_reset_token_repository.get_by_token_hash(
            db,
            _hash_reset_token(token),
        )

        now = datetime.now(timezone.utc)

        if (
            reset_token is None
            or reset_token.used_at is not None
            or reset_token.expires_at < now
        ):
            raise AuthenticationException("Invalid or expired reset link")

        user = await user_repository.get_by_id(db, reset_token.user_id)

        if user is None or not user.is_active:
            raise AuthenticationException("Invalid or expired reset link")

        user.password_hash = password_service.hash_password(new_password)

        await user_repository.update(db, user)
        await password_reset_token_repository.mark_used(db, reset_token, now)

    async def google_login(
        self,
        db: AsyncSession,
        google_id_token: str,
    ) -> TokenResponse:

        claims = verify_google_id_token(google_id_token)
        email = claims["email"]

        user = await user_repository.get_by_email(db, email)

        # Deliberate policy choice: Google sign-in only works for emails
        # that already have a PA-Copilot account — it never auto-creates
        # one. Auto-creating would also raise an unanswered question this
        # app's org-scoped RBAC model doesn't have a default for (which
        # organization would a brand-new Google user join?).
        if user is None:
            raise AuthenticationException(
                "No PA-Copilot account found for this email. Contact your "
                "administrator."
            )

        _check_can_authenticate(user)

        access_token = jwt_service.create_access_token(str(user.id))
        refresh_token = jwt_service.create_refresh_token(str(user.id))

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def get_current_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> UserResponse:

        user = await user_repository.get_by_id(
            db,
            user_id,
        )

        if user is None:
            raise NotFoundException("User not found")

        return UserResponse.model_validate(user)


auth_service = AuthService()