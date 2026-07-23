from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str
    last_name: str
    # A human-typeable invite code (Organization.code), not a raw UUID —
    # this is a self-service *request*, not an immediately-active account;
    # see registration_status on the resulting user.
    organization_code: str


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