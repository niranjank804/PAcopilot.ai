from pydantic import BaseModel, Field


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)


class UploadTarget(BaseModel):
    """Where to PUT the file and what to send with it. The key is what the
    client then hands to the endpoint that consumes the upload."""

    key: str
    url: str
    headers: dict[str, str]
    expires_in: int


class UploadedFile(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)


class UploadedFiles(BaseModel):
    uploads: list[UploadedFile] = Field(min_length=1, max_length=50)


class WorkbookFromUpload(UploadedFile):
    name: str | None = None
    description: str | None = None


class ArtifactFromUpload(UploadedFile):
    output_format: str
    checksum: str | None = None
