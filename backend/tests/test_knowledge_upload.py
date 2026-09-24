import io
import fitz  # PyMuPDF
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDoc
from app.services.rag_service import rag_service


@pytest.mark.asyncio
async def test_upload_text_document(client: AsyncClient, db_session: AsyncSession):
    """Verifies uploading and embedding a plain text document."""
    file_content = (
        "Warranty Policy for Electronics\n\n"
        "All smart electronics including earbuds, smartwatches, and chargers come with a 6-month official warranty. "
        "The warranty covers internal hardware malfunctions and battery failure. "
        "Physical damage, water exposure, and unauthorized repairs are not covered under this warranty.\n\n"
        "To claim warranty service, customers must present the original order number or invoice to our support team."
    )

    files = {
        "file": ("electronics_warranty.txt", io.BytesIO(file_content.encode("utf-8")), "text/plain"),
    }
    data = {
        "title": "Electronics 6-Month Warranty",
        "category": "warranty",
    }

    res = await client.post("/api/v1/knowledge/upload", files=files, data=data)
    assert res.status_code == 201

    resp_data = res.json()
    assert resp_data["status"] == "success"
    assert resp_data["title"] == "Electronics 6-Month Warranty"
    assert resp_data["category"] == "warranty"
    assert resp_data["chunks_count"] >= 1

    doc_id = resp_data["doc_id"]

    # Verify KnowledgeDoc and KnowledgeChunk in PostgreSQL
    doc = (await db_session.execute(select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id))).scalar_one_or_none()
    assert doc is not None
    assert doc.category == "warranty"

    chunks = (await db_session.execute(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))).scalars().all()
    assert len(chunks) == resp_data["chunks_count"]
    for chunk in chunks:
        assert chunk.embedding is not None  # Vector embedding successfully stored


@pytest.mark.asyncio
async def test_upload_pdf_document_and_vector_search(client: AsyncClient, db_session: AsyncSession):
    """
    Creates a real in-memory PDF using PyMuPDF, uploads it via the API,
    and runs a vector similarity search to verify RAG retrieval.
    """
    # 1. Generate an in-memory PDF using PyMuPDF
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page_text = (
        "Special Membership & VIP Lounge Perks\n\n"
        "Gold tier members receive 15 percent lifetime discount on all lifestyle accessories. "
        "VIP members also get free express same-day shipping inside Dhaka city. "
        "Exclusive early access to limited edition shoe drops is provided 24 hours in advance."
    )
    page.insert_text((50, 72), page_text, fontsize=12)
    pdf_bytes = pdf_doc.write()
    pdf_doc.close()

    # 2. Upload the PDF
    files = {
        "file": ("vip_membership_guide.pdf", io.BytesIO(pdf_bytes), "application/pdf"),
    }
    data = {
        "title": "VIP Membership Benefits",
        "category": "loyalty",
    }

    res = await client.post("/api/v1/knowledge/upload", files=files, data=data)
    assert res.status_code == 201
    resp_data = res.json()
    assert resp_data["chunks_count"] >= 1

    # 3. Test Vector Semantic Search against the uploaded PDF content
    results = await rag_service.search(
        db=db_session,
        query="What discount do Gold tier members get?",
        top_k=2,
    )

    assert len(results) > 0
    top_match = results[0]
    assert "15 percent lifetime discount" in top_match["content"]
    assert top_match["category"] == "loyalty"


@pytest.mark.asyncio
async def test_upload_unsupported_extension(client: AsyncClient):
    """Verifies that non-supported file formats (e.g. .png) are rejected with 400."""
    files = {
        "file": ("photo.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png"),
    }
    res = await client.post("/api/v1/knowledge/upload", files=files)
    assert res.status_code == 400
    assert "Unsupported file format" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_empty_document(client: AsyncClient):
    """Verifies that an empty text file is rejected with 400."""
    files = {
        "file": ("empty.txt", io.BytesIO(b"   "), "text/plain"),
    }
    res = await client.post("/api/v1/knowledge/upload", files=files)
    assert res.status_code == 400
    assert "contains no readable text" in res.json()["detail"]


@pytest.mark.asyncio
async def test_list_knowledge_documents(client: AsyncClient):
    """Verifies GET /api/v1/knowledge/docs returns indexed documents with chunk counts."""
    res = await client.get("/api/v1/knowledge/docs")
    assert res.status_code == 200
    docs = res.json()
    assert isinstance(docs, list)
    if docs:
        assert "id" in docs[0]
        assert "title" in docs[0]
        assert "chunks_count" in docs[0]