import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TicketStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"


class TicketUrgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class HandoffTicket(Base):
    """
    Human agent escalation tickets created when the AI cannot or should not proceed
    (customer request, high-risk dispute, repeated tool failure).
    """
    __tablename__ = "handoff_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=TicketStatus.PENDING.value,
        nullable=False,
        index=True,
        comment="PENDING, ASSIGNED, RESOLVED",
    )
    urgency: Mapped[str] = mapped_column(
        String(50),
        default=TicketUrgency.MEDIUM.value,
        nullable=False,
        index=True,
        comment="LOW, MEDIUM, HIGH, CRITICAL",
    )
    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Reason: customer_requested, price_dispute, refund_request, system_fallback",
    )
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="ID/Email of the human staff member handling this",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="AI-generated summary of the problem for the agent",
    )
    notes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Internal agent notes or resolution details",
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="handoff_tickets",
    )

    __table_args__ = (
        Index("ix_handoff_tickets_status_urgency", "status", "urgency"),
    )

    def __repr__(self) -> str:
        return f"<HandoffTicket {self.id} ({self.status}, {self.urgency}) - Reason: {self.reason}>"