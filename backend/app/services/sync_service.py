import logging
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product
from app.services.frappe_client import FrappeClient, frappe_client

logger = logging.getLogger(__name__)


class SyncService:
    """
    Synchronizes product catalog and stock from Frappe / ERPNext into local PostgreSQL.
    """

    def __init__(self, client: FrappeClient | None = None):
        self.client = client or frappe_client

    async def sync_catalog(self, db: AsyncSession, limit: int = 100) -> dict[str, Any]:
        """
        Pulls published items from Frappe and upserts them into the local products table.
        Attempts 'Website Item' first; if not present, falls back to 'Item'.
        """
        if not self.client.is_configured:
            logger.warning("Frappe API is not configured; skipping catalog sync.")
            return {"status": "skipped", "reason": "unconfigured"}

        logger.info(f"Starting catalog sync from {self.client.base_url} (limit: {limit})...")
        synced_count = 0
        created_count = 0
        updated_count = 0
        errors: list[str] = []

        # 1. Fetch items from Frappe (try Website Item, fallback to Item)
        raw_items: list[dict[str, Any]] = []
        try:
            raw_items = await self.client.list_website_items(limit=limit)
        except Exception as exc:
            logger.warning(f"Website Item query failed ({exc}), attempting standard Item doctype...")

        if not raw_items:
            try:
                import json
                filters = [["disabled", "=", 0]]
                fields = ["name", "item_code", "item_name", "item_group", "description", "standard_rate", "image"]
                res = await self.client._request(
                    "GET",
                    "/api/resource/Item",
                    params={"filters": json.dumps(filters), "fields": json.dumps(fields), "limit_page_length": limit}
                )
                raw_items = res.get("data", [])
            except Exception as exc:
                err_msg = f"Failed to fetch catalog from Frappe: {exc}"
                logger.error(err_msg)
                return {"status": "error", "error": err_msg}

        logger.info(f"Fetched {len(raw_items)} items from Frappe. Processing upserts...")

        # 2. Upsert each item into local database
        for item in raw_items:
            try:
                sku = item.get("item_code") or item.get("name")
                if not sku:
                    continue

                name = item.get("web_item_name") or item.get("item_name") or sku
                description = item.get("description") or ""
                price_val = Decimal(str(item.get("standard_rate") or item.get("price") or "0.00"))
                category = item.get("item_group")
                image = item.get("website_image") or item.get("image")
                route = item.get("route")
                product_url = f"{self.client.base_url}/{route.lstrip('/')}" if route else f"{self.client.base_url}/products/{sku}"

                # Check if exists
                stmt = select(Product).where(Product.sku == sku)
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.name = name
                    existing.description = description
                    existing.price = price_val
                    existing.category = category
                    existing.image_url = image
                    existing.product_url = product_url
                    existing.is_active = True
                    updated_count += 1
                else:
                    new_product = Product(
                        sku=sku,
                        name=name,
                        description=description,
                        price=price_val,
                        currency="BDT",
                        stock_quantity=10,  # Default baseline stock
                        is_active=True,
                        category=category,
                        product_url=product_url,
                        image_url=image,
                        attributes={"synced_from": "frappe"}
                    )
                    db.add(new_product)
                    created_count += 1

                synced_count += 1

            except Exception as item_exc:
                err_str = f"Error processing item {item.get('name')}: {item_exc}"
                logger.error(err_str)
                errors.append(err_str)

        await db.commit()
        logger.info(f"Catalog sync completed: {created_count} created, {updated_count} updated.")
        return {
            "status": "success",
            "total_synced": synced_count,
            "created": created_count,
            "updated": updated_count,
            "errors": errors,
        }


sync_service = SyncService()