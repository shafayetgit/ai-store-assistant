import hashlib
import hmac
import logging
import re
from typing import Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def clean_markdown_for_messenger(text: str) -> str:
    """
    Strips raw markdown formatting (bold **, italic *, headers #)
    that Facebook Messenger cannot render natively.
    """
    if not text:
        return ""

    # Remove bold: **word** or __word__ -> word
    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    clean = re.sub(r"__(.*?)__", r"\1", clean)

    # Remove italic: *word* or _word_ -> word
    clean = re.sub(r"\*(.*?)\*", r"\1", clean)
    clean = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", clean)

    # Remove markdown headers: ### Header -> Header
    clean = re.sub(r"^#{1,6}\s*", "", clean, flags=re.MULTILINE)

    # Clean inline code backticks: `code` -> code
    clean = re.sub(r"`(.*?)`", r"\1", clean)

    return clean.strip()


class MetaService:
    """
    Handles Meta Facebook Messenger Send API and Webhook HMAC SHA256 signature verification.
    """

    def __init__(self):
        self.app_secret = settings.META_APP_SECRET
        self.access_token = settings.META_PAGE_ACCESS_TOKEN
        self.api_version = settings.META_GRAPH_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    @property
    def is_configured(self) -> bool:
        """Returns True if Meta Page Access Token is provided."""
        return bool(self.access_token)

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str | None) -> bool:
        """
        Validates X-Hub-Signature-256 header using HMAC SHA-256.
        """
        if not self.app_secret:
            logger.warning("META_APP_SECRET not configured; skipping signature check in dev mode.")
            return True

        if not signature_header or not signature_header.startswith("sha256="):
            logger.error("Missing or invalid X-Hub-Signature-256 header format.")
            return False

        expected_sig = signature_header.split("sha256=")[1]
        calculated_sig = hmac.new(
            key=self.app_secret.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, calculated_sig)

    async def send_typing_indicator(self, recipient_psid: str, action: str = "typing_on") -> bool:
        """
        Sends typing indicator ('typing_on' or 'typing_off') to Facebook Messenger.
        """
        if not self.is_configured:
            logger.debug(f"[DEV DRY-RUN] Typing indicator '{action}' sent to PSID: {recipient_psid}")
            return True

        url = f"{self.base_url}/me/messages"
        params = {"access_token": self.access_token}
        payload = {
            "recipient": {"id": recipient_psid},
            "sender_action": action,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, params=params, json=payload)
                return res.status_code == 200
            except Exception as exc:
                logger.warning(f"Failed to send typing indicator to Meta: {exc}")
                return False

    async def send_message(
        self,
        recipient_psid: str,
        message_text: str,
        quick_replies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Sends text message and optional quick replies to a Facebook Messenger user.
        Splits messages exceeding 2000 characters to adhere to Messenger limits.
        """
        # Automatically clean out raw markdown asterisks for Messenger
        sanitized_text = clean_markdown_for_messenger(message_text)
        if not sanitized_text:
            logger.warning(f"Attempted to send empty message to PSID {recipient_psid}; skipping.")
            return {}

        if not self.is_configured:
            logger.info(f"[DEV DRY-RUN] Messenger reply to {recipient_psid}:\n{sanitized_text}")
            return {"recipient_id": recipient_psid, "message_id": "mid.mock_dev_id_12345"}

        url = f"{self.base_url}/me/messages"
        params = {"access_token": self.access_token}

        # Messenger max text character limit is 2000
        chunks = [sanitized_text[i:i + 1950] for i in range(0, len(sanitized_text), 1950)]
        last_res = {}

        async with httpx.AsyncClient(timeout=15.0) as client:
            for idx, chunk in enumerate(chunks):
                msg_payload: dict[str, Any] = {"text": chunk}
                if idx == len(chunks) - 1 and quick_replies:
                    msg_payload["quick_replies"] = quick_replies

                payload = {
                    "recipient": {"id": recipient_psid},
                    "messaging_type": "RESPONSE",
                    "message": msg_payload,
                }

                try:
                    res = await client.post(url, params=params, json=payload)
                    res.raise_for_status()
                    last_res = res.json()
                except httpx.HTTPStatusError as exc:
                    logger.error(f"Meta Send API error (HTTP {exc.response.status_code}): {exc.response.text}")
                    raise exc

        return last_res


meta_service = MetaService()


# <script 
#   src="http://localhost:8000/static/widget/chat-widget.js" 
#   data-api-base="http://localhost:8000" 
#   defer>
# </script>