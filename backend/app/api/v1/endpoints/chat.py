import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.customer import Customer, ChannelIdentity
from app.models.conversation import Conversation, ConversationState
from app.models.message import Message, SenderType
from app.models.handoff import HandoffTicket, TicketStatus, TicketUrgency
from app.services.agent_service import agent_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ━━ Request & Response Schemas ━━

class CreateSessionRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Existing browser session ID if returning visitor")
    visitor_name: str | None = Field(default=None, description="Optional visitor name")
    visitor_email: str | None = Field(default=None, description="Optional visitor email")
    current_url: str | None = Field(default=None, description="Current page URL visitor is browsing")


class SessionResponse(BaseModel):
    session_id: str
    conversation_id: str
    greeting: str
    quick_prompts: list[str]


class ChatStreamRequest(BaseModel):
    session_id: str
    message: str


class HandoffRequest(BaseModel):
    session_id: str | None = None
    reason: str | None = "Customer requested human support from web widget."


# ━━ Endpoints ━━

@router.post("/sessions", response_model=SessionResponse)
async def init_or_resume_session(
    payload: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """
    Initializes a new web chat session or resumes an existing active session.
    """
    session_id = payload.session_id or f"web_{uuid.uuid4().hex[:16]}"

    # 1. Resolve or create Customer & ChannelIdentity
    stmt = (
        select(ChannelIdentity)
        .options(selectinload(ChannelIdentity.customer))
        .where(
            ChannelIdentity.channel_type == "web",
            ChannelIdentity.channel_user_id == session_id,
        )
    )
    res = await db.execute(stmt)
    identity = res.scalar_one_or_none()

    if identity and identity.customer:
        customer = identity.customer
        if payload.visitor_name and customer.full_name in ("Website Visitor", "Valued Customer", None, ""):
            customer.full_name = payload.visitor_name
        if payload.visitor_email and not customer.email:
            customer.email = payload.visitor_email
        await db.commit()
    else:
        customer = Customer(
            full_name=payload.visitor_name or "Website Visitor",
            email=payload.visitor_email,
            metadata_info={"source": "web_chat", "initial_url": payload.current_url},
        )
        db.add(customer)
        await db.flush()

        identity = ChannelIdentity(
            customer_id=customer.id,
            channel_type="web",
            channel_user_id=session_id,
            profile_data={"session_id": session_id, "current_url": payload.current_url},
        )
        db.add(identity)
        await db.flush()

    # 2. Resolve or create active Conversation
    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.customer_id == customer.id,
            Conversation.channel_type == "webchat",
            Conversation.session_state != ConversationState.RESOLVED.value,
        )
        .order_by(Conversation.created_at.desc())
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalars().first()

    if not conversation:
        conversation = Conversation(
            customer_id=customer.id,
            channel_type="webchat",
            session_state=ConversationState.AI_ACTIVE.value,
            metadata_info={"current_url": payload.current_url},
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    return SessionResponse(
        session_id=session_id,
        conversation_id=str(conversation.id),
        greeting="👋 Hi there! Welcome to our store. How can I help you today?",
        quick_prompts=[
            "Do you have any wireless earbuds?",
            "Where is my order SO-2026-0042?",
            "What are your delivery charges?",
            "Talk to a human agent",
        ],
    )


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns the customer-facing message history for a web session (filters out internal tool calls).
    """
    id_stmt = select(ChannelIdentity).where(
        ChannelIdentity.channel_type == "web",
        ChannelIdentity.channel_user_id == session_id,
    )
    res = await db.execute(id_stmt)
    identity = res.scalar_one_or_none()

    if not identity:
        return {"session_id": session_id, "messages": []}

    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.customer_id == identity.customer_id,
            Conversation.channel_type == "webchat",
        )
        .order_by(Conversation.created_at.desc())
    )
    conv = (await db.execute(conv_stmt)).scalars().first()
    if not conv:
        return {"session_id": session_id, "messages": []}

    msg_stmt = (
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.sender_type.in_([SenderType.USER.value, SenderType.ASSISTANT.value, SenderType.HUMAN_AGENT.value]),
        )
        .order_by(Message.created_at.asc())
    )
    messages = (await db.execute(msg_stmt)).scalars().all()

    return {
        "session_id": session_id,
        "conversation_id": str(conv.id),
        "session_state": conv.session_state,
        "messages": [
            {
                "id": str(m.id),
                "role": "user" if m.sender_type == SenderType.USER.value else "assistant",
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
            if m.content
        ],
    }


@router.post("/sessions/{session_id}/handoff")
async def request_handoff(
    session_id: str,
    payload: HandoffRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Flags the conversation for human customer service takeover.
    """
    id_stmt = select(ChannelIdentity).where(
        ChannelIdentity.channel_type == "web",
        ChannelIdentity.channel_user_id == session_id,
    )
    identity = (await db.execute(id_stmt)).scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="Session not found")

    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.customer_id == identity.customer_id,
            Conversation.channel_type == "webchat",
        )
        .order_by(Conversation.created_at.desc())
    )
    conv = (await db.execute(conv_stmt)).scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.session_state = ConversationState.HUMAN_REQUESTED.value

    ticket = HandoffTicket(
        conversation_id=conv.id,
        reason=payload.reason or "Customer requested human support.",
        urgency=TicketUrgency.MEDIUM.value,
        status=TicketStatus.PENDING.value,
    )
    db.add(ticket)
    await db.commit()

    return {
        "status": "handed_off",
        "message": "A customer care representative has been notified and will assist you shortly.",
    }


@router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE Token Streaming endpoint.
    Performs autonomous tool reasoning loop and streams tokens in real-time.
    """
    id_stmt = (
        select(ChannelIdentity)
        .options(selectinload(ChannelIdentity.customer))
        .where(
            ChannelIdentity.channel_type == "web",
            ChannelIdentity.channel_user_id == payload.session_id,
        )
    )
    identity = (await db.execute(id_stmt)).scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="Session not found. Please initialize session first.")

    conv_stmt = (
        select(Conversation)
        .options(selectinload(Conversation.customer))
        .where(
            Conversation.customer_id == identity.customer_id,
            Conversation.channel_type == "webchat",
            Conversation.session_state != ConversationState.RESOLVED.value,
        )
        .order_by(Conversation.created_at.desc())
    )
    conv = (await db.execute(conv_stmt)).scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Active conversation not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in agent_service.stream_message(db, conv, payload.message):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'status': 'done'})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error(f"Error during SSE stream: {exc}", exc_info=True)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sync-catalog",
    summary="Synchronize product catalog from ERPNext/Frappe into local database",
)
async def sync_catalog(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Triggers catalog synchronization from the configured Frappe/ERPNext instance.
    Pulls items/website items and upserts them into the PostgreSQL products table.
    """
    from app.services.sync_service import sync_service
    result = await sync_service.sync_catalog(db=db, limit=limit)
    return result