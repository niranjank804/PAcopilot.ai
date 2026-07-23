import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str
    port: int = 443
    ssl: bool = True
    username: str = "apikey"
    password: str
    authentication_type: Literal["native", "v12_saas"] = "native"
    tenant: str | None = None
    database: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = None
    port: int | None = None
    ssl: bool | None = None
    username: str | None = None
    # Only re-encrypted and stored if provided — omit to keep the existing
    # credential (never round-tripped back to the client, so there's nothing
    # to prefill on an edit form; leaving it blank means "no change").
    password: str | None = None
    authentication_type: Literal["native", "v12_saas"] | None = None
    tenant: str | None = None
    database: str | None = None


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    port: int
    ssl: bool
    username: str
    is_active: bool
    authentication_type: str
    tenant: str | None
    database: str | None


class TestConnectionResponse(BaseModel):
    connected: bool


class CubeResponse(BaseModel):
    name: str
    dimensions: list[str]
    has_rules: bool


class DimensionResponse(BaseModel):
    name: str
    hierarchy_names: list[str]


class ExtractionSummaryResponse(BaseModel):
    objects_created: int
    relationships_created: int


class ProcessResponse(BaseModel):
    name: str
    datasource_type: str
    datasource_name: str
    datasource_view: str
    has_security_access: bool
    parameter_names: list[str]
    prolog: str
    metadata: str
    data: str
    epilog: str


class CubeRulesResponse(BaseModel):
    name: str
    rules: str | None


class ChoreResponse(BaseModel):
    name: str
    active: bool
    process_names: list[str]


class RelatedObject(BaseModel):
    relationship_type: str
    object_type: str
    name: str


class ObjectRelationshipsResponse(BaseModel):
    object_type: str
    name: str
    outgoing: list[RelatedObject]
    incoming: list[RelatedObject]


class DependencyNode(BaseModel):
    object_type: str
    name: str
    relationship_type: str
    via: str
    depth: int


class PathNode(BaseModel):
    object_type: str
    name: str


class DependencyPathResponse(BaseModel):
    found: bool
    path: list[PathNode]


class UnusedObject(BaseModel):
    object_type: str
    name: str


class SecurityGroupResponse(BaseModel):
    name: str
    member_user_names: list[str]


class VisualizeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class VisualizeCell(BaseModel):
    label: str
    value: float


class VisualizeResponse(BaseModel):
    cube_name: str
    mdx: str
    summary: str
    cells: list[VisualizeCell]


class ChangeCreate(BaseModel):
    change_type: Literal[
        "update_rules", "create_process", "update_process", "delete_process"
    ]
    target_name: str = Field(min_length=1, max_length=255)
    new_content: dict | None = None


class ChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    change_type: str
    target_name: str
    status: str
    new_content: dict | None
    previous_content: dict | None
    validation_errors: list | None
    impact: list | None
    error_message: str | None
    created_by: uuid.UUID
    executed_by: uuid.UUID | None
    created_at: datetime
    executed_at: datetime | None
    rolled_back_at: datetime | None


class ChangeDetailResponse(BaseModel):
    change: ChangeResponse
    preview: dict
