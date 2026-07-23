import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class TM1Relationship(BaseModel):
    __tablename__ = "tm1_relationships"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tm1_connections.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    from_object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tm1_objects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    to_object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tm1_objects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    relationship_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
