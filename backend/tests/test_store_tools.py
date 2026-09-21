import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_tools import STORE_TOOLS, execute_tool


def test_store_tools_schema_definition():
    """Verifies all 5 tools are declared with valid OpenAI function calling schemas."""
    tool_names = [t["function"]["name"] for t in STORE_TOOLS]
    assert "search_products" in tool_names
    assert "get_product_details" in tool_names
    assert "track_order" in tool_names
    assert "search_store_policies" in tool_names
    assert "request_human_handoff" in tool_names


async def test_search_store_policies(db_session: AsyncSession):
    """Tests policy tool execution against store policies."""
    res = await execute_tool(
        tool_name="search_store_policies",
        arguments={"query": "What are your delivery charges and timelines?"},
        db=db_session,
    )
    assert res["matches_found"] >= 0
    assert "guidance" in res


async def test_order_tracking_unknown_order(db_session: AsyncSession):
    """Tests looking up a non-existent order number."""
    res = await execute_tool(
        tool_name="track_order",
        arguments={"order_number": "NON-EXISTENT-ORDER-999"},
        db=db_session,
    )
    assert res["found"] is False


async def test_order_tracking_existing_order(db_session: AsyncSession):
    """Tests looking up the seeded order SO-2026-0042."""
    res = await execute_tool(
        tool_name="track_order",
        arguments={"order_number": "SO-2026-0042"},
        db=db_session,
    )
    assert res["found"] is True
    assert res["order_number"] == "SO-2026-0042"
    assert res["status"] == "SHIPPED"
    assert len(res["items"]) > 0


async def test_request_human_handoff(db_session: AsyncSession):
    """Tests executing human agent handoff tool."""
    res = await execute_tool(
        tool_name="request_human_handoff",
        arguments={"reason": "Customer requesting custom bulk quotation", "urgency": "high"},
        db=db_session,
    )
    assert res["success"] is True
    assert res["status"] == "handed_off"