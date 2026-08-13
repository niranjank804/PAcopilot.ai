import uuid

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class TM1Process(BaseModel, OrganizationScoped):
    """A parsed TurboIntegrator process, kept so later phases can use it.

    Structure only. The source code is deliberately not stored: it is already
    in the customer's TM1 server and their source control, it may embed
    credentials, and duplicating it here would make this table a second place
    a secret can leak from without making any downstream feature possible.
    """

    __tablename__ = "tm1_processes"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_tm1_processes_org_name"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    source_file: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=text("''")
    )

    datasource_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="none", server_default=text("'none'")
    )

    header_comment: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    # Whether the export this was parsed from carried datasource credentials.
    # The values are never read; the flag lets an operator find which exports
    # need treating as secret.
    has_stored_credentials: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )

    line_counts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )

    parameters: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    # Object references as the parser emitted them: name, kind, access,
    # section, and whether the name was a literal. Non-literal names are
    # variables resolved at runtime and cannot be matched to a real object
    # without live server metadata, so the flag has to survive.
    objects: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    functions_used: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )

    process_calls: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    object_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class TM1ProcessPattern(BaseModel, OrganizationScoped):
    """A pattern a process was found to implement, with its evidence.

    One row per (process, pattern): a process genuinely implements several at
    once — an ODBC loader that also maintains a dimension and cleans up after
    itself — and collapsing that to a single label would discard most of what
    was measured.
    """

    __tablename__ = "tm1_process_patterns"
    __table_args__ = (
        UniqueConstraint(
            "process_id",
            "pattern_key",
            name="uq_tm1_process_patterns_process_key",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tm1_processes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pattern_key: Mapped[str] = mapped_column(String(50), nullable=False)

    score: Mapped[float] = mapped_column(nullable=False)

    # The signals that produced the match. A pattern claim you cannot justify
    # to a TM1 developer is worse than no claim.
    evidence: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
