import uuid

from pydantic import BaseModel, ConfigDict


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    description: str | None


class RolePermissionAssign(BaseModel):
    permission_id: uuid.UUID
