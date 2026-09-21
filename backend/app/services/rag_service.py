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
        query_vector = await embedding_service.get_embedding(query)

        # 1. pgvector cosine similarity search
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

        chunks: list[dict[str, Any]] = []
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


rag_service = RAGService()