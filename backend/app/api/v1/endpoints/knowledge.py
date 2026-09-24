import logging
from uuid import UUID
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.knowledge import KnowledgeChunk, KnowledgeDoc
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload and embed a PDF, TXT, or Markdown document into vector DB",
)
async def upload_knowledge_document(
    file: UploadFile = File(..., description="Document file (.pdf, .txt, or .md)"),
    title: str | None = Form(default=None, description="Optional custom document title"),
    category: str = Form(
        default="general",
        description="Category (e.g., 'shipping', 'returns', 'faq', 'warranty')",
    ),
    source_url: str | None = Form(default=None, description="Optional source web URL"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Receives a PDF, TXT, or Markdown file, extracts text, chunks it,
    generates vector embeddings via Ollama / LLM Gateway, and stores it in pgvector.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty.",
        )

    # Read file bytes in memory
    try:
        content = await file.read()
    except Exception as exc:
        logger.error(f"Failed to read uploaded file: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {exc}",
        )

    # Enforce file size limit
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    # Ingest through RAG Service
    try:
        result = await rag_service.ingest_document(
            db=db,
            file_bytes=content,
            filename=file.filename,
            title=title,
            category=category,
            source_url=source_url,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as exc:
        logger.error(f"Unexpected error ingesting '{file.filename}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process and embed document: {exc}",
        )


@router.get(
    "/docs",
    summary="List all stored knowledge documents and their chunk counts",
)
async def list_knowledge_documents(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Returns all indexed knowledge documents with category, chunk count, and created timestamp.
    """
    stmt = (
        select(
            KnowledgeDoc,
            func.count(KnowledgeChunk.id).label("chunk_count"),
        )
        .outerjoin(KnowledgeChunk, KnowledgeChunk.doc_id == KnowledgeDoc.id)
        .group_by(KnowledgeDoc.id)
        .order_by(KnowledgeDoc.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(doc.id),
            "title": doc.title,
            "category": doc.category,
            "source_url": doc.source_url,
            "chunks_count": chunk_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc, chunk_count in rows
    ]



@router.get(
    "/docs/{doc_id}/chunks",
    summary="Get all chunks and metadata for a specific document",
)
async def get_document_chunks(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns the full text chunks, titles, and embedding status for a given document.
    """
    doc_stmt = select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id)
    doc = (await db.execute(doc_stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    chunks_stmt = (
        select(KnowledgeChunk)
        .where(KnowledgeChunk.doc_id == doc_id)
        .order_by(KnowledgeChunk.created_at.asc())
    )
    chunks = (await db.execute(chunks_stmt)).scalars().all()
    return {
        "doc_id": str(doc.id),
        "title": doc.title,
        "category": doc.category,
        "total_chunks": len(chunks),
        "chunks": [
            {
                "id": str(c.id),
                "title": c.title,
                "content": c.content,
                "has_embedding": c.embedding is not None,
                "metadata_info": c.metadata_info,
            }
            for c in chunks
        ],
    }


@router.delete(
    "/docs",
    summary="Delete ALL knowledge documents and vector chunks",
)
async def delete_all_knowledge_documents(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Deletes all knowledge documents and their vector chunks from pgvector.
    """
    # Delete chunks and documents
    res_chunks = await db.execute(delete(KnowledgeChunk))
    res_docs = await db.execute(delete(KnowledgeDoc))
    await db.commit()

    return {
        "status": "success",
        "deleted_docs_count": res_docs.rowcount,
        "deleted_chunks_count": res_chunks.rowcount,
        "message": f"Successfully deleted {res_docs.rowcount} documents and {res_chunks.rowcount} vector chunks.",
    }


@router.delete(
    "/docs/{doc_id}",
    summary="Delete a specific knowledge document and its chunks",
)
async def delete_single_knowledge_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Deletes a single document and cascades deletion to all its vector chunks.
    """
    doc_stmt = select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id)
    doc = (await db.execute(doc_stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    title = doc.title
    await db.delete(doc)
    await db.commit()

    return {
        "status": "success",
        "doc_id": str(doc_id),
        "message": f"Successfully deleted document '{title}' and its associated vector chunks.",
    }