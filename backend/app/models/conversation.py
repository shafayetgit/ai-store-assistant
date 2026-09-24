import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConversationState(str, Enum):
    AI_ACTIVE = "AI_ACTIVE"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    RESOLVED = "RESOLVED"


class Conversation(Base):
    """
    Represents a conversation session between a customer and the assistant.
    Governed by the session state machine (AI_ACTIVE <-> HUMAN_ACTIVE).
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="messenger, webchat, whatsapp",
    )
    session_state: Mapped[str] = mapped_column(
        String(50),
        default=ConversationState.AI_ACTIVE.value,
        nullable=False,
        index=True,
        comment="AI_ACTIVE, HUMAN_REQUESTED, HUMAN_ACTIVE, RESOLVED",
    )
    metadata_info: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Extra session context (e.g. current page URL, browser)",
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="conversations",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )
    handoff_tickets: Mapped[list["HandoffTicket"]] = relationship(
        "HandoffTicket",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_conversations_customer_state", "customer_id", "session_state"),
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.id} (channel={self.channel_type}, state={self.session_state})>"