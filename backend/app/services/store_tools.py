import json
import logging
import uuid
from typing import Any
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.order import Order, OrderItem
from app.models.handoff import HandoffTicket, TicketStatus, TicketUrgency
from app.models.conversation import Conversation, ConversationState
from app.services.rag_service import rag_service
from app.services.frappe_client import frappe_client

logger = logging.getLogger(__name__)

# ━━ 1. Tool Schemas (OpenAI / Ollama Function Calling Format) ━━
STORE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the online store catalog by product name, category, or price range. Always use this when a customer asks for recommendations, available items, or pricing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for (e.g. 'earbuds', 'hoodie', 't-shirt', 'protector').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g. 'Apparel', 'Electronics', 'Footwear', 'Lifestyle', 'Protector').",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Optional maximum price filter in store currency (BDT).",
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "If true, returns only items currently in stock. Defaults to false so customers can learn about out-of-stock or upcoming items.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Fetch detailed specifications, size/color variant options, and exact stock for a specific product by SKU / Item Code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {
                        "type": "string",
                        "description": "The SKU or Item Code (e.g. 'TSH-BLK-001', 'STO-ITEM-2026-00001').",
                    }
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "track_order",
            "description": "Check the delivery status, tracking number, courier partner, and items for an existing order by order number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {
                        "type": "string",
                        "description": "The Store Order Number (e.g. 'SO-2026-0042').",
                    },
                    "contact": {
                        "type": "string",
                        "description": "Optional phone number or email of the customer for identity verification.",
                    },
                },
                "required": ["order_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_store_policies",
            "description": "Search store knowledge base: company profile, about us, founder/CEO, team, branch locations & addresses, phone numbers, shipping charges, delivery timeframes, return/refund policy, and payment methods.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The knowledge base query (e.g. 'who is CEO', 'branch locations', 'Bali Arcade address', 'delivery fee inside Dhaka', 'return policy').",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_handoff",
            "description": "Escalate the conversation to a human customer care agent. Use this when the customer explicitly asks to talk to a human, or has an unresolved dispute or complex complaint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why handoff is requested (e.g. 'Customer requested human agent', 'Dispute over damaged product').",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "critical"],
                        "description": "Priority level of the handoff request.",
                        "default": "normal",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]


# ━━ 2. Tool Implementation Handlers ━━

async def handle_search_products(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    query_str = (args.get("query") or "").strip()
    category = args.get("category")
    max_price = args.get("max_price")
    in_stock_only = args.get("in_stock_only", False)

    stmt = select(Product).where(Product.is_active.is_(True))

    if query_str:
        words = [w.strip() for w in query_str.split() if len(w.strip()) > 1]
        if words:
            word_conditions = []
            for w in words:
                p = f"%{w}%"
                word_conditions.append(
                    or_(
                        Product.name.ilike(p),
                        Product.description.ilike(p),
                        Product.category.ilike(p),
                        Product.sku.ilike(p),
                    )
                )
            stmt = stmt.where(and_(*word_conditions))

    if category:
        stmt = stmt.where(Product.category.ilike(f"%{category}%"))

    if max_price is not None:
        try:
            stmt = stmt.where(Product.price <= float(max_price))
        except (ValueError, TypeError):
            pass

    if in_stock_only:
        stmt = stmt.where(Product.stock_quantity > 0)

    stmt = stmt.order_by(Product.stock_quantity.desc()).limit(8)
    result = await db.execute(stmt)
    products = result.scalars().all()

    items = []
    for p in products:
        specs = (p.attributes or {}).get("specifications", {})
        is_available = p.stock_quantity > 0
        items.append({
            "sku": p.sku,
            "name": p.name,
            "price": float(p.price),
            "currency": p.currency,
            "in_stock": is_available,
            "stock_status": "In Stock ✅" if is_available else "Out of Stock ❌",
            "category": p.category,
            "description": p.description,
            "specifications": specs,
            "url": p.product_url,
            "image": p.image_url,
        })

    return {
        "count": len(items),
        "products": items,
        "note": "Mention product name, price in BDT, and links when recommending to customers.",
    }


async def handle_get_product_details(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    sku = (args.get("sku") or "").strip()
    if not sku:
        return {"found": False, "message": "Product SKU was not specified."}

    stmt = select(Product).where(Product.sku.ilike(sku))
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        return {"found": False, "message": f"Product with SKU '{sku}' was not found."}

    is_available = product.stock_quantity > 0
    return {
        "found": True,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "price": float(product.price),
        "currency": product.currency,
        "in_stock": is_available,
        "stock_status": "In Stock ✅" if is_available else "Out of Stock ❌",
        "category": product.category,
        "attributes": product.attributes or {},
        "product_url": product.product_url,
        "image_url": product.image_url,
    }


async def handle_track_order(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    order_num = (args.get("order_number") or "").strip()
    contact = args.get("contact")

    if not order_num:
        return {"found": False, "message": "Please provide an order number (e.g. SO-2026-0042) to track."}

    # 1. Check local PostgreSQL database
    stmt = select(Order).where(Order.order_number.ilike(order_num))
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if order:
        items_stmt = select(OrderItem).where(OrderItem.order_id == order.id)
        items_res = await db.execute(items_stmt)
        items = items_res.scalars().all()

        return {
            "found": True,
            "order_number": order.order_number,
            "status": order.status,
            "tracking_code": order.tracking_code or "Pending courier dispatch",
            "total_amount": float(order.total_amount),
            "currency": order.currency,
            "delivery_address": order.delivery_address,
            "estimated_delivery": order.estimated_delivery.isoformat() if order.estimated_delivery else "1-2 business days",
            "items": [{"item_name": it.item_name, "quantity": it.quantity, "total": float(it.total_price)} for it in items],
        }

    # 2. Fallback: Query live Frappe / ERPNext backend
    try:
        remote_order = await frappe_client.get_sales_order(order_num)
        if remote_order:
            return {
                "found": True,
                "order_number": remote_order.get("name"),
                "status": remote_order.get("status", "PROCESSING"),
                "tracking_code": remote_order.get("tracking_code", "Dispatched via store courier"),
                "total_amount": float(remote_order.get("grand_total", 0)),
                "currency": remote_order.get("currency", "BDT"),
                "delivery_address": remote_order.get("shipping_address", ""),
                "items": [{"item_name": it.get("item_name"), "quantity": it.get("qty")} for it in remote_order.get("items", [])],
            }
    except Exception as exc:
        logger.warning(f"Remote order lookup failed: {exc}")

    return {
        "found": False,
        "message": f"Order '{order_num}' could not be found. Please ask customer to double check the order number.",
    }


async def handle_search_policies(db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return {
            "query": "",
            "matches_found": 0,
            "policies": [],
            "guidance": "Please ask a specific store question regarding shipping, returns, warranty, or payment.",
        }
    results = await rag_service.search(db, query=query, top_k=3)
    return {
        "query": query,
        "matches_found": len(results),
        "policies": results,
        "guidance": "Answer the customer accurately based on these store policies. Do not invent fees or conditions.",
    }


async def handle_human_handoff(
    db: AsyncSession,
    args: dict[str, Any],
    conversation_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    reason = args.get("reason", "Customer requested human support.")
    urgency_str = args.get("urgency", "normal").lower()

    urgency_map = {
        "low": TicketUrgency.LOW,
        "normal": TicketUrgency.MEDIUM,
        "high": TicketUrgency.HIGH,
        "critical": TicketUrgency.CRITICAL,
    }
    urgency = urgency_map.get(urgency_str, TicketUrgency.MEDIUM)

    ticket_id = str(uuid.uuid4())

    # If active conversation exists, record persistent ticket in DB
    if conversation_id:
        if isinstance(conversation_id, str):
            try:
                conversation_id = uuid.UUID(conversation_id)
            except ValueError:
                conversation_id = None

    if conversation_id:
        ticket = HandoffTicket(
            id=uuid.UUID(ticket_id),
            conversation_id=conversation_id,
            reason=reason,
            urgency=urgency.value,
            status=TicketStatus.PENDING.value,
            summary=args.get("summary", reason),
        )
        db.add(ticket)

        conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
        conv_res = await db.execute(conv_stmt)
        conv = conv_res.scalar_one_or_none()
        if conv:
            conv.session_state = ConversationState.HUMAN_REQUESTED.value

        await db.commit()

    # Create support issue in Frappe / ERPNext
    try:
        if frappe_client.is_configured:
            await frappe_client.create_issue(
                subject=f"Customer Handoff: {reason[:60]}",
                description=f"Automated handoff created for conversation {conversation_id}.\nReason: {reason}",
                raised_by="store-bot@aistore.local",
                priority="Urgent" if urgency_str in ("high", "critical") else "Medium",
            )
    except Exception as exc:
        logger.warning(f"Could not create Frappe issue for handoff: {exc}")

    return {
        "success": True,
        "ticket_id": ticket_id,
        "status": "handed_off",
        "message": "A human customer care agent has been notified and will take over this conversation.",
    }


# ━━ 3. Tool Dispatcher ━━

async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    db: AsyncSession,
    conversation_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """
    Executes the specified tool and returns JSON response for the LLM.
    """
    logger.info(f"Executing tool '{tool_name}' with args: {arguments}")

    if tool_name == "search_products":
        return await handle_search_products(db, arguments)
    elif tool_name == "get_product_details":
        return await handle_get_product_details(db, arguments)
    elif tool_name == "track_order":
        return await handle_track_order(db, arguments)
    elif tool_name == "search_store_policies":
        return await handle_search_policies(db, arguments)
    elif tool_name == "request_human_handoff":
        return await handle_human_handoff(db, arguments, conversation_id, customer_id)
    else:
        return {"error": f"Unknown tool name '{tool_name}'."}