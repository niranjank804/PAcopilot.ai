from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str
    last_name: str
    # A human-typeable invite code (Organization.code), not a raw UUID.
    # Optional for now (testing phase, user's explicit choice): omitted,
    # every signup lands in the single default org and is auto-approved -
    # see auth_service.register(). Still accepted explicitly for a future
    # multi-org / admin-approval mode without a schema change.
    organization_code: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class GoogleLoginRequest(BaseModel):
    id_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    is_active: bool
    organization_id: UUID
    registration_status: str


class ApproveUserRequest(BaseModel):
    role_id: UUID | None = None