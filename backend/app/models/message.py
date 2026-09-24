import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SenderType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    HUMAN_AGENT = "human_agent"


class Message(Base):
    """
    Represents an individual message turn inside a conversation.
    Stores human text, AI responses, tool invocations, and raw channel payloads.
    """
    __tablename__ = "messages"

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
    sender_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="user, assistant, system, tool, human_agent",
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Textual content of the message",
    )
    tool_calls: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Structured tool calls executed by LLM",
    )
    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Raw incoming/outgoing channel payload (Meta mid, quick replies)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        snippet = (self.content[:30] + "...") if self.content else "[no text]"
        return f"<Message {self.id} ({self.sender_type}): {snippet}>"