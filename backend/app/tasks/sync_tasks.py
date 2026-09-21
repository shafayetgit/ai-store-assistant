import asyncio
import logging
from typing import Any
from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.services.sync_service import sync_service

logger = logging.getLogger(__name__)


async def _async_sync_catalog(limit: int = 100) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        return await sync_service.sync_catalog(db=session, limit=limit)


@celery_app.task(name="tasks.sync_store_catalog")
def sync_store_catalog(limit: int = 100) -> dict[str, Any]:
    """
    Celery background/cron task that pulls the latest items from ERPNext
    and upserts them into the PostgreSQL database.
    """
    logger.info(f"Running periodic catalog sync (limit={limit})...")
    try:
        res = asyncio.run(_async_sync_catalog(limit=limit))
        logger.info(f"Catalog sync completed: {res}")
        return res
    except Exception as exc:
        logger.error(f"Catalog sync failed: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}

