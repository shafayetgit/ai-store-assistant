import asyncio
import json
import time
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.customer import ChannelIdentity
from app.models.conversation import Conversation
from app.models.message import Message
from app.tasks.messenger_tasks import _async_process_messenger_message

async def simulate_messenger():
    print("=" * 65)
    print("📱 SIMULATING FACEBOOK MESSENGER WEBHOOK PIPELINE")
    print("=" * 65)

    test_psid = f"fb_user_sim_{int(time.time())}"
    user_question = "Do you have any black t-shirts in stock?"

    # 1. Simulate Meta delivering a webhook event to FastAPI
    print(f"\n1. Meta delivering webhook event for PSID: {test_psid}...")
    print(f"   Customer text: \"{user_question}\"")

    payload = {
        "object": "page",
        "entry": [{
            "messaging": [{
                "sender": {"id": test_psid},
                "recipient": {"id": "store_page_id_999"},
                "message": {
                    "mid": f"mid_test_{int(time.time())}",
                    "text": user_question,
                }
            }]
        }]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/webhooks/messenger", json=payload)
        print(f"   Webhook HTTP Response: {res.status_code} {res.json()}")

    # 2. Process the task (executes customer resolution + LLM tool loop)
    print("\n2. Processing Celery pipeline (Customer Resolution + AI Agent)...")
    task_res = await _async_process_messenger_message(
        sender_psid=test_psid,
        message_text=user_question,
        message_id=payload["entry"][0]["messaging"][0]["message"]["mid"],
    )
    print(f"   Pipeline Status: {task_res.get('status')}")

    # 3. Verify Database Records
    print("\n3. Verifying Persisted Omnichannel State in PostgreSQL...")
    async with AsyncSessionLocal() as session:
        # Check ChannelIdentity
        id_stmt = select(ChannelIdentity).where(ChannelIdentity.channel_user_id == test_psid)
        identity = (await session.execute(id_stmt)).scalar_one_or_none()
        print(f"   ✅ ChannelIdentity: {identity.channel_type} | User ID: {identity.channel_user_id}")

        # Check Conversation
        conv_stmt = select(Conversation).where(Conversation.customer_id == identity.customer_id)
        conv = (await session.execute(conv_stmt)).scalars().first()
        print(f"   ✅ Conversation ID: {conv.id} | Channel: {conv.channel_type} | State: {conv.session_state}")

        # Check Messages History
        msg_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        messages = (await session.execute(msg_stmt)).scalars().all()
        print(f"\n4. Stored Conversation Transcript ({len(messages)} messages):")
        for m in messages:
            print(f"   [{m.sender_type.upper()}]: {m.content[:100] if m.content else (m.tool_calls or '')}")

    print("\n🎉 Facebook Messenger integration verified end-to-end!")

if __name__ == "__main__":
    asyncio.run(simulate_messenger())