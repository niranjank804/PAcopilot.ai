import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    is_system: bool


class UserRoleAssign(BaseModel):
    role_id: uuid.UUID
