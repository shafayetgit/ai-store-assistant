import logging
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.config import settings
from app.tasks.sync_tasks import sync_product_event

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_frappe_webhook_secret(
    x_frappe_webhook_secret: str | None,
    authorization: str | None,
) -> bool:
    """
    Validates webhook secret against settings.STORE_WEBHOOK_SECRET if configured.
    Supports either 'X-Frappe-Webhook-Secret' or 'Authorization: Bearer <secret>'.
    """
    expected_secret = settings.STORE_WEBHOOK_SECRET
    if not expected_secret:
        return True

    if x_frappe_webhook_secret and x_frappe_webhook_secret.strip() == expected_secret:
        return True

    if authorization:
        token = authorization.strip()
        if token.startswith("Bearer "):
            token = token[7:].strip()
        if token == expected_secret:
            return True

    return False


@router.post(
    "/frappe/product",
    status_code=status.HTTP_200_OK,
    summary="ERPNext / Frappe product update webhook",
)
async def handle_frappe_product_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_frappe_webhook_secret: str | None = Header(default=None, alias="X-Frappe-Webhook-Secret"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Receives real-time product events (insert, update, trash) from Frappe/ERPNext Webhooks.
    Asynchronously synchronizes the item and updates local vector/relational catalog.
    """
    if not verify_frappe_webhook_secret(x_frappe_webhook_secret, authorization):
        logger.warning("Rejected Frappe webhook: invalid or missing webhook secret header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret header.",
        )

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.error(f"Invalid JSON in Frappe product webhook payload: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body.")

    # Extract doc data (supporting either nested 'doc' or top-level payload)
    doc = payload.get("doc") if isinstance(payload.get("doc"), dict) else payload
    sku = str(doc.get("item_code") or doc.get("name") or doc.get("sku") or payload.get("item_code") or "").strip()

    if not sku:
        logger.error("Frappe product webhook missing 'item_code' or 'name'.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'item_code' or 'name' in webhook payload.",
        )

    event = str(payload.get("event") or doc.get("event") or "on_update").strip().lower()

    # Dispatch to Celery worker (or background task fallback if Celery/Redis is unreachable)
    try:
        sync_product_event.delay(sku=sku, event=event, payload=doc)
        logger.info(f"Enqueued Celery product sync task for SKU: {sku} (event: {event})")
    except Exception as exc:
        logger.warning(f"Celery enqueue failed ({exc}); falling back to local BackgroundTasks.")
        background_tasks.add_task(sync_product_event, sku, event, doc)

    return {
        "status": "queued",
        "sku": sku,
        "event": event,
    }

