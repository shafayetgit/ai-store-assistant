import uuid
from datetime import datetime
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base


class KnowledgeDoc(Base):
    """
    Parent knowledge document (e.g. 'Return Policy', 'Shipping Guide', 'Store FAQs').
    """
    __tablename__ = "knowledge_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="shipping, returns, faq, payment, store_hours",
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="doc",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDoc {self.id} ({self.title} - {self.category})>"


class KnowledgeChunk(Base):
    """
    Chunked sections of knowledge documents embedded using pgvector.
    Searched via cosine similarity for grounding LLM replies.
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_docs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # pgvector embedding column with dimension from settings (default: 768)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSION), nullable=True)

    metadata_info: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Chunk metadata: section headers, page, keywords",
    )

    # Relationships
    doc: Mapped["KnowledgeDoc"] = relationship(
        "KnowledgeDoc",
        back_populates="chunks",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeChunk {self.id} (Doc: {self.doc_id}, Title: {self.title[:30]})>"