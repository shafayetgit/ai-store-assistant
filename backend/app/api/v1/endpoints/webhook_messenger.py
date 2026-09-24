import json
import logging
import time
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.services.meta_service import meta_service
from app.tasks.messenger_tasks import process_messenger_message_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/messenger", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
) -> str:
    """
    Meta Webhook Verification Handshake.
    Facebook sends a GET request to verify our webhook URL during setup.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Meta webhook verification challenge passed successfully.")
        return hub_challenge

    logger.warning(f"Failed Meta webhook verification. Received token: '{hub_verify_token}'")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch",
    )


@router.post("/messenger")
async def receive_messenger_event(
    request: Request,
    x_hub_signature: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """
    Receives incoming messaging events from Facebook Messenger.
    Verifies HMAC SHA-256 signature and offloads processing to Celery (<50ms response).
    Supports both text messages and button postbacks.
    """
    body_bytes = await request.body()

    # 1. Verify HMAC SHA-256 Signature
    if not meta_service.verify_webhook_signature(body_bytes, x_hub_signature):
        logger.error("Invalid Meta X-Hub-Signature-256 signature on incoming webhook.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 2. Extract and Enqueue Messaging Events
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message_obj = messaging.get("message")
                postback_obj = messaging.get("postback")

                user_text = None
                message_id = None

                # Support both direct text messages and button/quick-reply postbacks
                if message_obj and "text" in message_obj:
                    user_text = message_obj["text"]
                    message_id = message_obj.get("mid")
                elif postback_obj:
                    user_text = postback_obj.get("payload") or postback_obj.get("title")
                    message_id = f"mid_pb_{sender_id}_{messaging.get('timestamp', int(time.time() * 1000))}"

                if sender_id and user_text:
                    if not message_id:
                        message_id = f"mid_{sender_id}_{int(time.time() * 1000)}"

                    logger.info(f"Enqueueing Messenger message from PSID {sender_id}: '{user_text[:50]}'...")

                    # Offload to Celery background worker
                    process_messenger_message_task.delay(
                        sender_psid=sender_id,
                        message_text=user_text,
                        message_id=message_id,
                    )

        # Meta requires an immediate HTTP 200 OK
        return {"status": "EVENT_RECEIVED"}

    raise HTTPException(status_code=404, detail="Not a page subscription")