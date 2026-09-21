import asyncio
import concurrent.futures
import logging
from typing import Any
import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.celery import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.customer import Customer, ChannelIdentity
from app.models.conversation import Conversation, ConversationState
from app.services.agent_service import agent_service
from app.services.meta_service import meta_service

logger = logging.getLogger(__name__)


async def _async_process_messenger_message(sender_psid: str, message_text: str, message_id: str) -> dict[str, Any]:
    """
    Asynchronously handles deduplication, customer identity resolution,
    AI reasoning, and dispatching reply back to Facebook Messenger.
    """
    try:
        # 1. Deduplication via loop-scoped Redis connection
        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            dedup_key = f"msg_dedup:messenger:{message_id}"
            is_new = await redis.set(dedup_key, "1", nx=True, ex=3600)
            if not is_new:
                logger.info(f"Duplicate Messenger event {message_id} ignored.")
                return {"status": "skipped", "reason": "duplicate"}
        finally:
            await redis.aclose()

        async with AsyncSessionLocal() as session:
            # 2. Resolve or create Customer & ChannelIdentity
            stmt = (
                select(ChannelIdentity)
                .options(selectinload(ChannelIdentity.customer))
                .where(
                    ChannelIdentity.channel_type == "facebook",
                    ChannelIdentity.channel_user_id == sender_psid,
                )
            )
            res = await session.execute(stmt)
            identity = res.scalar_one_or_none()

            if identity and identity.customer:
                customer = identity.customer
            else:
                customer = Customer(
                    full_name=f"Facebook User ({sender_psid[-4:]})",
                    metadata_info={"source": "facebook_messenger"},
                )
                session.add(customer)
                await session.flush()

                identity = ChannelIdentity(
                    customer_id=customer.id,
                    channel_type="facebook",
                    channel_user_id=sender_psid,
                    profile_data={"psid": sender_psid},
                )
                session.add(identity)
                await session.flush()

            # 3. Resolve active Conversation
            conv_stmt = (
                select(Conversation)
                .where(
                    Conversation.customer_id == customer.id,
                    Conversation.channel_type == "messenger",
                    Conversation.session_state != ConversationState.RESOLVED.value,
                )
                .order_by(Conversation.created_at.desc())
            )
            conv_res = await session.execute(conv_stmt)
            conversation = conv_res.scalars().first()

            if not conversation:
                conversation = Conversation(
                    customer_id=customer.id,
                    channel_type="messenger",
                    session_state=ConversationState.AI_ACTIVE.value,
                )
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)

            # 4. Send typing indicator
            await meta_service.send_typing_indicator(sender_psid, "typing_on")

            # 5. Execute AI Agent reasoning loop
            ai_reply = await agent_service.process_message(
                db=session,
                conversation=conversation,
                user_text=message_text,
            )

            # 6. Deliver reply to customer on Messenger
            send_res = {}
            if ai_reply:
                send_res = await meta_service.send_message(
                    recipient_psid=sender_psid,
                    message_text=ai_reply,
                )

            # 7. Turn typing indicator off
            await meta_service.send_typing_indicator(sender_psid, "typing_off")

            return {
                "status": "success",
                "sender_psid": sender_psid,
                "message_id": message_id,
                "reply_length": len(ai_reply),
                "meta_res": send_res,
            }
    finally:
        # Clean up database connection pool before the event loop ends
        await engine.dispose()


@celery_app.task(name="tasks.process_messenger_message", bind=True, max_retries=2)
def process_messenger_message_task(self, sender_psid: str, message_text: str, message_id: str) -> dict[str, Any]:
    """
    Celery synchronous entrypoint.
    Safely executes the async pipeline whether called from a Celery worker or an active asyncio event loop.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_process_messenger_message(sender_psid, message_text, message_id))
                return future.result()
        else:
            return asyncio.run(_async_process_messenger_message(sender_psid, message_text, message_id))

    except httpx.HTTPStatusError as exc:
        logger.error(f"HTTP error sending to Meta (HTTP {exc.response.status_code}): {exc.response.text}")
        # Do not retry on 4xx client errors (e.g. invalid recipient ID from unit tests)
        if exc.response.status_code < 500:
            return {"status": "error", "code": exc.response.status_code, "detail": exc.response.text}
        raise self.retry(exc=exc, countdown=5)

    except Exception as exc:
        logger.error(f"Error processing Messenger task: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=5)