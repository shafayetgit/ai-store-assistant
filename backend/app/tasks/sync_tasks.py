import asyncio
import concurrent.futures
import logging
from typing import Any
from app.core.celery import celery_app
from app.core.database import TaskSessionLocal
from app.services.sync_service import sync_service

logger = logging.getLogger(__name__)


async def _async_sync_catalog(limit: int = 100) -> dict[str, Any]:
    async with TaskSessionLocal() as session:
        return await sync_service.sync_catalog(db=session, limit=limit)


@celery_app.task(name="tasks.sync_store_catalog")
def sync_store_catalog(limit: int = 100) -> dict[str, Any]:
    """
    Celery background/cron task that pulls the latest items from ERPNext
    and upserts them into the PostgreSQL database.
    Safely executes whether called from Celery worker or an active asyncio loop.
    """
    logger.info(f"Running periodic catalog sync (limit={limit})...")
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_sync_catalog(limit=limit))
                res = future.result()
        else:
            res = asyncio.run(_async_sync_catalog(limit=limit))

        logger.info(f"Catalog sync completed: {res}")
        return res
    except Exception as exc:
        logger.error(f"Catalog sync failed: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}


async def _async_sync_product(sku: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with TaskSessionLocal() as session:
        return await sync_service.sync_single_product(
            db=session,
            sku=sku,
            event=event,
            doc_data=payload,
        )


@celery_app.task(name="tasks.sync_product_event")
def sync_product_event(sku: str, event: str = "on_update", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Celery task to handle an incoming product webhook event from ERPNext / Frappe.
    Safely executes across event loops using TaskSessionLocal (NullPool).
    """
    payload = payload or {}
    logger.info(f"Processing product webhook event '{event}' for SKU: {sku}")
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_sync_product(sku, event, payload))
                return future.result()
        else:
            return asyncio.run(_async_sync_product(sku, event, payload))
    except Exception as exc:
        logger.error(f"Failed to process product event for {sku}: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc), "sku": sku}

