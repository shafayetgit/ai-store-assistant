import hashlib
import hmac
import json
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.meta_service import meta_service


def test_hmac_signature_verification():
    """Tests cryptographic signature validation for Meta webhooks."""
    secret = "unit_test_secret_key"
    meta_service.app_secret = secret
    payload = b'{"object": "page", "entry": []}'

    valid_sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    invalid_sig = "sha256=1234567890abcdef"

    assert meta_service.verify_webhook_signature(payload, valid_sig) is True
    assert meta_service.verify_webhook_signature(payload, invalid_sig) is False
    assert meta_service.verify_webhook_signature(payload, None) is False


async def test_meta_dry_run_send():
    """Tests Meta Graph Send API dry-run output in non-production environments."""
    original_token = meta_service.access_token
    try:
        meta_service.access_token = ""
        res = await meta_service.send_message(
            recipient_psid="test_recipient_psid_101",
            message_text="Hello from Pytest!",
        )
        assert res["recipient_id"] == "test_recipient_psid_101"
        assert "mid." in res["message_id"]
    finally:
        meta_service.access_token = original_token


async def test_messenger_webhook_get_handshake(client: AsyncClient):
    """Tests GET /api/v1/webhooks/messenger subscription verification."""
    token = settings.META_VERIFY_TOKEN
    challenge = "CHALLENGE_STRING_12345"

    # 1. Valid handshake
    res = await client.get(
        "/api/v1/webhooks/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": token,
            "hub.challenge": challenge,
        },
    )
    assert res.status_code == 200
    assert res.text == challenge

    # 2. Invalid verify token
    res_bad = await client.get(
        "/api/v1/webhooks/messenger",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": challenge,
        },
    )
    assert res_bad.status_code == 403

    # 3. Invalid mode
    res_invalid_mode = await client.get(
        "/api/v1/webhooks/messenger",
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": token,
            "hub.challenge": challenge,
        },
    )
    assert res_invalid_mode.status_code == 403


async def test_messenger_webhook_post_ingestion(client: AsyncClient):
    """Tests POST /api/v1/webhooks/messenger event ingestion."""
    event_body = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "messaging": [
                    {
                        "sender": {"id": "fb_user_test_999"},
                        "recipient": {"id": "page_123"},
                        "message": {
                            "mid": "mid.test_event_001",
                            "text": "Do you have any items in stock?",
                        },
                    }
                ],
            }
        ],
    }

    raw_bytes = json.dumps(event_body).encode("utf-8")
    secret = "test_meta_app_secret_123"
    meta_service.app_secret = secret
    sig = "sha256=" + hmac.new(secret.encode(), raw_bytes, hashlib.sha256).hexdigest()

    res = await client.post(
        "/api/v1/webhooks/messenger",
        content=raw_bytes,
        headers={"x-hub-signature-256": sig, "content-type": "application/json"},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "EVENT_RECEIVED"}


async def test_messenger_webhook_postback_ingestion(client: AsyncClient):
    """Tests POST /api/v1/webhooks/messenger postback button event ingestion."""
    event_body = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "messaging": [
                    {
                        "sender": {"id": "fb_user_postback_888"},
                        "recipient": {"id": "page_123"},
                        "postback": {
                            "title": "Get Started",
                            "payload": "GET_STARTED_PAYLOAD",
                        },
                    }
                ],
            }
        ],
    }

    raw_bytes = json.dumps(event_body).encode("utf-8")
    secret = "test_meta_app_secret_123"
    meta_service.app_secret = secret
    sig = "sha256=" + hmac.new(secret.encode(), raw_bytes, hashlib.sha256).hexdigest()

    res = await client.post(
        "/api/v1/webhooks/messenger",
        content=raw_bytes,
        headers={"x-hub-signature-256": sig, "content-type": "application/json"},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "EVENT_RECEIVED"}