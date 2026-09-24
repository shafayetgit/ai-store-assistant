import pytest
from httpx import AsyncClient


async def test_create_and_resume_session(client: AsyncClient):
    """Tests session initialization and customer identity generation."""
    # 1. Initialize session for new visitor
    res = await client.post(
        "/api/v1/chat/sessions",
        json={"visitor_name": "Farhana Ahmed", "current_url": "http://localhost/products/apparel"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "conversation_id" in data
    assert len(data["quick_prompts"]) > 0

    session_id = data["session_id"]

    # 2. Resume same session with existing session_id
    res_resume = await client.post(
        "/api/v1/chat/sessions",
        json={"session_id": session_id, "visitor_name": "Farhana Ahmed"},
    )
    assert res_resume.status_code == 200
    assert res_resume.json()["session_id"] == session_id


async def test_session_history_and_handoff(client: AsyncClient):
    """Tests customer history retrieval and human agent handoff escalation."""
    # 1. Create a session
    s_res = await client.post(
        "/api/v1/chat/sessions",
        json={"visitor_name": "Tanvir Hossain"},
    )
    session_id = s_res.json()["session_id"]

    # 2. Retrieve history (should start empty)
    h_res = await client.get(f"/api/v1/chat/sessions/{session_id}/history")
    assert h_res.status_code == 200
    assert h_res.json()["session_id"] == session_id
    assert isinstance(h_res.json()["messages"], list)

    # 3. Request human handoff
    ho_res = await client.post(
        f"/api/v1/chat/sessions/{session_id}/handoff",
        json={"reason": "Customer needs custom bulk pricing."},
    )
    assert ho_res.status_code == 200
    assert ho_res.json()["status"] == "handed_off"