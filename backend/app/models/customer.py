import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Customer(Base):
    """
    Represents a unified store customer profile.
    Can be linked to multiple channel identities (Messenger PSID, Web session, etc.).
    """
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Optional metadata (e.g. VIP tag, preferences, notes)
    metadata_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    # Relationships
    channel_identities: Mapped[list["ChannelIdentity"]] = relationship(
        "ChannelIdentity",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="customer",
    )

    def __repr__(self) -> str:
        return f"<Customer {self.id} (name={self.full_name}, email={self.email})>"


class ChannelIdentity(Base):
    """
    Maps an external channel identifier to a Customer.
    Examples:
    - channel_type="messenger", channel_user_id="9876543210" (Meta PSID)
    - channel_type="webchat", channel_user_id="web_a8b7c6d5-..." (Website token)
    """
    __tablename__ = "channel_identities"

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
    channel_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="External user ID (Meta PSID, web session UUID, phone)",
    )
    profile_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Raw profile payload from channel (e.g. Facebook first/last name)",
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="channel_identities",
    )

    __table_args__ = (
        # Ensure a channel user ID is unique within a channel type
        Index("ix_channel_identities_type_user", "channel_type", "channel_user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ChannelIdentity {self.channel_type}:{self.channel_user_id} -> Customer {self.customer_id}>"