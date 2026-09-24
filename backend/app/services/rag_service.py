from pathlib import Path
from app.services.document_parser import extract_text_from_file
from app.services.text_chunker import chunk_text

import logging
from typing import Any
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDoc
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class RAGService:
    """
    Semantic search and document indexing using pgvector cosine distance.
    """

    def __init__(self):
        self.top_k = settings.RAG_TOP_K
        self.similarity_threshold = settings.RAG_SIMILARITY_THRESHOLD

    async def search(
        self,
        db: AsyncSession,
        query: str,
        top_k: int | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieves top relevant knowledge chunks matching the user's natural language query.
        Uses pgvector cosine distance with fallback to SQL keyword search.
        """
        k = top_k or self.top_k
        chunks: list[dict[str, Any]] = []

        # 1. pgvector cosine similarity search
        try:
            query_vector = await embedding_service.get_embedding(query)

            # In pgvector: cosine_distance is 1 - cosine_similarity.
            # So cosine_similarity = 1 - (embedding <=> query_vector)
            distance_col = KnowledgeChunk.embedding.cosine_distance(query_vector).label("distance")

            stmt = (
                select(KnowledgeChunk, KnowledgeDoc, distance_col)
                .join(KnowledgeDoc, KnowledgeChunk.doc_id == KnowledgeDoc.id)
                .where(KnowledgeChunk.embedding.is_not(None))
            )

            if category:
                stmt = stmt.where(KnowledgeDoc.category == category)

            stmt = stmt.order_by(distance_col).limit(k)
            result = await db.execute(stmt)
            rows = result.all()

            for chunk, doc, dist in rows:
                similarity = 1.0 - float(dist)
                if similarity >= self.similarity_threshold:
                    chunks.append({
                        "id": str(chunk.id),
                        "title": chunk.title,
                        "doc_title": doc.title,
                        "category": doc.category,
                        "content": chunk.content,
                        "similarity": round(similarity, 4),
                        "source_url": doc.source_url,
                    })
        except Exception as vec_err:
            logger.warning(f"Vector search failed for '{query}': {vec_err}. Falling back to keyword search.")

        # 2. Resilient Fallback: If no vector matches found, use keyword search
        if not chunks:
            logger.info(f"Vector search returned no results for '{query}'. Running keyword fallback...")
            terms = [f"%{term}%" for term in query.strip().split() if len(term) > 2]
            if terms:
                kw_conditions = []
                for t in terms:
                    kw_conditions.append(KnowledgeChunk.content.ilike(t))
                    kw_conditions.append(KnowledgeChunk.title.ilike(t))

                kw_stmt = (
                    select(KnowledgeChunk, KnowledgeDoc)
                    .join(KnowledgeDoc, KnowledgeChunk.doc_id == KnowledgeDoc.id)
                    .where(or_(*kw_conditions))
                    .limit(k)
                )
                kw_result = await db.execute(kw_stmt)
                for chunk, doc in kw_result.all():
                    chunks.append({
                        "id": str(chunk.id),
                        "title": chunk.title,
                        "doc_title": doc.title,
                        "category": doc.category,
                        "content": chunk.content,
                        "similarity": 0.50,  # Baseline score for keyword matches
                        "source_url": doc.source_url,
                    })

        return chunks

    async def embed_unembedded_chunks(self, db: AsyncSession) -> int:
        """
        Finds all knowledge chunks without vector embeddings and populates them.
        """
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.embedding.is_(None))
        result = await db.execute(stmt)
        chunks = result.scalars().all()

        if not chunks:
            logger.info("All knowledge chunks are already embedded.")
            return 0

        logger.info(f"Generating embeddings for {len(chunks)} knowledge chunks...")
        texts = [f"{c.title}\n{c.content}" for c in chunks]
        vectors = await embedding_service.get_embeddings(texts)

        for chunk, vec in zip(chunks, vectors):
            chunk.embedding = vec

        await db.commit()
        logger.info(f"Successfully embedded and saved {len(chunks)} chunks.")
        return len(chunks)


    async def ingest_document(
        self,
        db: AsyncSession,
        file_bytes: bytes,
        filename: str,
        title: str | None = None,
        category: str = "general",
        source_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Parses an uploaded file (PDF, TXT, MD), splits it into semantic chunks,
        generates vector embeddings, and stores both document and chunks in pgvector.

        Args:
            db: Database session.
            file_bytes: In-memory raw bytes of the file.
            filename: Original file name.
            title: Optional human-readable document title (defaults to cleaned filename).
            category: Document category (e.g., 'shipping', 'returns', 'faq', 'warranty').
            source_url: Optional link to the live online policy page.

        Returns:
            Dictionary with ingestion summary (doc_id, title, category, chunks_count).
        """
        # 1. Parse text from file bytes
        raw_text = extract_text_from_file(file_bytes=file_bytes, filename=filename)

        # 2. Determine document title
        doc_title = (title or Path(filename).stem.replace("-", " ").replace("_", " ")).strip().title()
        doc_category = (category or "general").strip().lower()

        # 3. Chunk text into semantic pieces
        chunks_data = chunk_text(raw_text, doc_title=doc_title)
        if not chunks_data:
            raise ValueError(f"No valid text chunks could be produced from '{filename}'.")

        logger.info(f"Ingesting document '{doc_title}' ({len(chunks_data)} chunks) into category '{doc_category}'...")

        # 4. Create the parent KnowledgeDoc
        doc = KnowledgeDoc(
            title=doc_title,
            category=doc_category,
            source_url=source_url,
        )
        db.add(doc)
        await db.flush()  # Flushes to generate doc.id without committing

        # 5. Generate vector embeddings in batch
        texts_to_embed = [f"{c['title']}\n{c['content']}" for c in chunks_data]
        vectors = await embedding_service.get_embeddings(texts_to_embed)

        # 6. Create KnowledgeChunk records with vector embeddings
        chunk_objects: list[KnowledgeChunk] = []
        for idx, (chunk_dict, vector) in enumerate(zip(chunks_data, vectors)):
            chunk_obj = KnowledgeChunk(
                doc_id=doc.id,
                title=chunk_dict["title"],
                content=chunk_dict["content"],
                embedding=vector,
                metadata_info={
                    "source_file": filename,
                    "chunk_index": idx + 1,
                    "total_chunks": len(chunks_data),
                    "category": doc_category,
                },
            )
            chunk_objects.append(chunk_obj)

        db.add_all(chunk_objects)
        await db.commit()
        await db.refresh(doc)

        logger.info(f"Successfully ingested '{doc_title}' with {len(chunk_objects)} embedded chunks.")

        return {
            "status": "success",
            "doc_id": str(doc.id),
            "title": doc.title,
            "category": doc.category,
            "chunks_count": len(chunk_objects),
            "filename": filename,
        }

rag_service = RAGService()