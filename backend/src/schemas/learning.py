from pydantic import BaseModel


class ConventionResponse(BaseModel):
    key: str
    statement: str
    confidence: float
    support: int
    sample: int
    examples: list[str]
    counter_examples: list[str]


class PatternCountResponse(BaseModel):
    key: str
    name: str
    description: str
    process_count: int


class RejectedFileResponse(BaseModel):
    filename: str
    reason: str


class LearningRunResponse(BaseModel):
    processes_parsed: int
    processes_failed: int
    conventions_learned: int
    patterns: list[PatternCountResponse]
    rejected: list[RejectedFileResponse]
    # Exports carry datasource credentials. The count is reported so an
    # uploader learns the files they just handled are secret material; the
    # values themselves are never read.
    files_with_stored_credentials: int


class StandardsResponse(BaseModel):
    process_count: int
    conventions: list[ConventionResponse]


class StandardsReportResponse(BaseModel):
    markdown: str
