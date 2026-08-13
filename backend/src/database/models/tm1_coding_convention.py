import uuid

from sqlalchemy import (
    Float,
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


class TM1CodingConvention(BaseModel, OrganizationScoped):
    """A coding convention measured from an organization's own TI processes.

    Each row is an observation, not a policy: `support` of `sample` processes
    followed the rule. Storing the counts alongside the statement is what lets
    the assistant say "your team does this in 59 of 64 processes" instead of
    asserting a house style nobody agreed to — and lets a reviewer disagree
    with the evidence rather than with the model.
    """

    __tablename__ = "tm1_coding_conventions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "convention_key",
            name="uq_tm1_coding_conventions_org_key",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    convention_key: Mapped[str] = mapped_column(String(100), nullable=False)

    statement: Mapped[str] = mapped_column(Text, nullable=False)

    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    support: Mapped[int] = mapped_column(Integer, nullable=False)

    sample: Mapped[int] = mapped_column(Integer, nullable=False)

    # Process names on each side of the observation. Names only — never source
    # code, which may carry embedded credentials or business logic that has no
    # reason to be duplicated out of the knowledge base.
    examples: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    counter_examples: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
