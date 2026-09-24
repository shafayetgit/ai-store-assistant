import html
import logging
import re
from decimal import Decimal
from typing import Any
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product
from app.services.frappe_client import FrappeClient, frappe_client

logger = logging.getLogger(__name__)


def clean_html(raw_html: str | None) -> str:
    """Strips HTML tags and unescapes HTML entities to clean plain text."""
    if not raw_html:
        return ""
    # Convert list items to bullet points
    text = re.sub(r"<li[^>]*>", "\n• ", raw_html, flags=re.IGNORECASE)
    # Convert breaks and paragraphs to newlines
    text = re.sub(r"</?(?:p|br|div|tr|h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities (&nbsp;, &amp;, etc.)
    text = html.unescape(text)
    # Normalize excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class SyncService:
    """
    Synchronizes comprehensive product catalog, rich technical specifications,
    pricing, and stock inventory from Frappe / ERPNext into local PostgreSQL.
    """

    def __init__(self, client: FrappeClient | None = None):
        self.client = client or frappe_client

    async def sync_catalog(self, db: AsyncSession, limit: int = 100) -> dict[str, Any]:
        """
        Pulls published items from Frappe and upserts them into the local products table.
        Captures rich descriptions, website specifications, live prices, and warehouse stock.
        """
        if not self.client.is_configured:
            logger.warning("Frappe API is not configured; skipping catalog sync.")
            return {"status": "skipped", "reason": "unconfigured"}

        logger.info(f"Starting deep catalog sync from {self.client.base_url} (limit: {limit})...")
        synced_count = 0
        created_count = 0
        updated_count = 0
        errors: list[str] = []

        # 1. Fetch website items list
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
                    params={"filters": json.dumps(filters), "fields": json.dumps(fields), "limit_page_length": limit},
                )
                raw_items = res.get("data", [])
            except Exception as exc:
                err_msg = f"Failed to fetch catalog from Frappe: {exc}"
                logger.error(err_msg)
                return {"status": "error", "error": err_msg}

        logger.info(f"Fetched {len(raw_items)} items from Frappe. Processing deep specifications...")

        # 2. Upsert each item with full specifications
        for item in raw_items:
            try:
                sku = str(item.get("item_code") or item.get("name") or "").strip()
                if not sku:
                    continue

                web_item_name = item.get("name") or sku

                # Fetch full Website Item document for child tables (specifications, long descriptions)
                full_web_doc: dict[str, Any] = {}
                try:
                    full_web_doc = await self.client.get_full_website_item(web_item_name) or {}
                except Exception as doc_exc:
                    logger.debug(f"Could not fetch full Website Item for {web_item_name}: {doc_exc}")

                # Resolve title
                name = (
                    full_web_doc.get("web_item_name")
                    or item.get("web_item_name")
                    or item.get("item_name")
                    or sku
                )

                # Parse & clean descriptions and specifications
                main_desc = clean_html(
                    full_web_doc.get("web_long_description")
                    or full_web_doc.get("description")
                    or item.get("description")
                    or ""
                )

                specifications: dict[str, str] = {}
                spec_lines: list[str] = []
                for spec in full_web_doc.get("website_specifications", []):
                    label = str(spec.get("label") or "").strip()
                    val = clean_html(spec.get("description") or "")
                    if label and val:
                        specifications[label] = val
                        spec_lines.append(f"• {label}: {val}")

                # Build comprehensive product description for AI grounding
                desc_parts: list[str] = []
                if main_desc:
                    desc_parts.append(main_desc)
                if spec_lines:
                    desc_parts.append("Specifications & Features:\n" + "\n".join(spec_lines))

                final_description = "\n\n".join(desc_parts)

                # Resolve live price & warehouse stock
                price_and_stock = await self.client.get_item_price_and_stock(sku)
                price_val = Decimal(str(price_and_stock["price"]))
                currency = price_and_stock["currency"]
                stock_qty = price_and_stock["stock_quantity"]

                # If standard_rate is non-zero and Item Price was 0, fall back to standard_rate
                if price_val == Decimal("0.00"):
                    fallback_rate = item.get("standard_rate") or full_web_doc.get("standard_rate")
                    if fallback_rate:
                        price_val = Decimal(str(fallback_rate))

                category = full_web_doc.get("item_group") or item.get("item_group")
                image = full_web_doc.get("website_image") or item.get("website_image") or item.get("image")
                if image and image.startswith("/"):
                    image = f"{self.client.base_url}{image}"

                route = full_web_doc.get("route") or item.get("route")
                product_url = f"{self.client.base_url}/{route.lstrip('/')}" if route else f"{self.client.base_url}/products/{sku}"

                # Structured attributes
                attributes = {
                    "specifications": specifications,
                    "brand": full_web_doc.get("brand") or item.get("brand"),
                    "stock_uom": full_web_doc.get("stock_uom") or item.get("stock_uom") or "Nos",
                    "has_variants": bool(full_web_doc.get("has_variants")),
                    "route": route,
                }

                # Check if product already exists
                stmt = select(Product).where(Product.sku == sku)
                existing = (await db.execute(stmt)).scalar_one_or_none()

                if existing:
                    existing.name = name
                    existing.description = final_description
                    existing.price = price_val
                    existing.currency = currency
                    existing.stock_quantity = stock_qty
                    existing.category = category
                    existing.image_url = image
                    existing.product_url = product_url
                    existing.attributes = attributes
                    existing.is_active = True
                    updated_count += 1
                else:
                    new_product = Product(
                        sku=sku,
                        name=name,
                        description=final_description,
                        price=price_val,
                        currency=currency,
                        stock_quantity=stock_qty,
                        is_active=True,
                        category=category,
                        product_url=product_url,
                        image_url=image,
                        attributes=attributes,
                    )
                    db.add(new_product)
                    created_count += 1

                # If the item has variants, sync all child variants (published or unpublished)
                has_variants = bool(full_web_doc.get("has_variants") or item.get("has_variants"))
                if has_variants:
                    v_created, v_updated = await self._sync_item_variants(
                        db=db,
                        template_item_code=sku,
                        parent_specs=specifications,
                        parent_desc=final_description,
                        parent_category=category,
                        parent_route=route,
                        parent_image=image,
                    )
                    created_count += v_created
                    updated_count += v_updated
                    synced_count += (v_created + v_updated)

                synced_count += 1

            except Exception as item_exc:
                err_str = f"Error processing item {item.get('name')}: {item_exc}"
                logger.error(err_str, exc_info=True)
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

    async def sync_single_product(
        self,
        db: AsyncSession,
        sku: str,
        event: str = "on_update",
        doc_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Synchronizes a single product with full specifications, pricing, and stock.
        Handles on_trash or disabled=1 by deactivating the product.
        """
        sku = (sku or "").strip()
        if not sku:
            return {"status": "error", "reason": "empty_sku"}

        event = (event or "on_update").lower()
        doc_data = doc_data or {}

        # 1. Soft-delete if trashed or disabled
        is_disabled = bool(doc_data.get("disabled") == 1 or doc_data.get("disabled") is True)
        if event in ("on_trash", "trash", "delete") or is_disabled:
            stmt = select(Product).where(Product.sku == sku)
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.is_active = False
                await db.commit()
                logger.info(f"Product {sku} deactivated (event: {event}).")
                return {"status": "deactivated", "sku": sku}
            return {"status": "not_found", "sku": sku}

        # 2. Enrich with live ERPNext Website Item details
        full_web_doc: dict[str, Any] = {}
        if self.client.is_configured:
            try:
                # Try finding Website Item by sku
                import json
                res = await self.client._request(
                    "GET",
                    "/api/resource/Website Item",
                    params={"filters": json.dumps([["item_code", "=", sku]]), "limit_page_length": 1},
                )
                web_items = res.get("data", [])
                if web_items:
                    full_web_doc = await self.client.get_full_website_item(web_items[0]["name"]) or {}
                else:
                    # Fallback to standard Item doctype
                    live_item = await self.client.get_item(sku)
                    if live_item:
                        full_web_doc = live_item
            except Exception as exc:
                logger.warning(f"Could not fetch full details for {sku} from Frappe API: {exc}")

        # Merge webhook payload with fetched doc
        item = dict(full_web_doc)
        item.update({k: v for k, v in doc_data.items() if v is not None})

        name = item.get("web_item_name") or item.get("item_name") or sku

        # Parse & clean descriptions and specifications
        main_desc = clean_html(
            item.get("web_long_description")
            or item.get("description")
            or ""
        )

        specifications: dict[str, str] = {}
        spec_lines: list[str] = []
        for spec in item.get("website_specifications", []):
            label = str(spec.get("label") or "").strip()
            val = clean_html(spec.get("description") or "")
            if label and val:
                specifications[label] = val
                spec_lines.append(f"• {label}: {val}")

        desc_parts: list[str] = []
        if main_desc:
            desc_parts.append(main_desc)
        if spec_lines:
            desc_parts.append("Specifications & Features:\n" + "\n".join(spec_lines))

        final_description = "\n\n".join(desc_parts)

        # Resolve live price & stock
        price_and_stock = await self.client.get_item_price_and_stock(sku)
        price_val = Decimal(str(price_and_stock["price"]))
        currency = price_and_stock["currency"]
        stock_qty = price_and_stock["stock_quantity"]

        if price_val == Decimal("0.00"):
            fallback_rate = item.get("standard_rate") or item.get("price")
            if fallback_rate:
                price_val = Decimal(str(fallback_rate))

        category = item.get("item_group")
        image = item.get("website_image") or item.get("image")
        if image and image.startswith("/"):
            image = f"{self.client.base_url}{image}"

        route = item.get("route")
        product_url = f"{self.client.base_url}/{route.lstrip('/')}" if route else f"{self.client.base_url}/products/{sku}"

        attributes = {
            "specifications": specifications,
            "brand": item.get("brand"),
            "stock_uom": item.get("stock_uom") or "Nos",
            "has_variants": bool(item.get("has_variants")),
            "route": route,
        }

        stmt = select(Product).where(Product.sku == sku)
        existing = (await db.execute(stmt)).scalar_one_or_none()

        action = "updated" if existing else "created"
        if existing:
            existing.name = name
            existing.description = final_description
            existing.price = price_val
            existing.currency = currency
            existing.stock_quantity = stock_qty
            existing.category = category
            existing.image_url = image
            existing.product_url = product_url
            existing.attributes = attributes
            existing.is_active = True
        else:
            new_product = Product(
                sku=sku,
                name=name,
                description=final_description,
                price=price_val,
                currency=currency,
                stock_quantity=stock_qty,
                is_active=True,
                category=category,
                product_url=product_url,
                image_url=image,
                attributes=attributes,
            )
            db.add(new_product)

        # If the item is a template with variants, sync its variants as well
        has_variants = bool(item.get("has_variants"))
        if has_variants:
            await self._sync_item_variants(
                db=db,
                template_item_code=sku,
                parent_specs=specifications,
                parent_desc=final_description,
                parent_category=category,
                parent_route=route,
                parent_image=image,
            )

        await db.commit()
        logger.info(f"Product {sku} {action} with full specifications via sync.")
        return {"status": action, "sku": sku}


    async def _sync_item_variants(
        self,
        db: AsyncSession,
        template_item_code: str,
        parent_specs: dict[str, str],
        parent_desc: str,
        parent_category: str,
        parent_route: str | None,
        parent_image: str | None,
    ) -> tuple[int, int]:
        """
        Fetches and upserts all variant items for a template product.
        Returns (created_count, updated_count).
        """
        created = 0
        updated = 0

        variants = await self.client.get_item_variants(template_item_code)
        for var in variants:
            var_sku = var.get("item_code") or var.get("name")
            if not var_sku:
                continue

            var_name = var.get("item_name") or var_sku
            var_category = var.get("item_group") or parent_category

            # Extract variant attributes (e.g., Colour: White, Size: Small)
            var_attrs: dict[str, Any] = {}
            for attr_row in var.get("attributes_list", []):
                attr_name = attr_row.get("attribute")
                attr_val = attr_row.get("attribute_value")
                if attr_name and attr_val:
                    var_attrs[attr_name] = attr_val

            # Resolve price and stock for this specific variant
            pricing_info = await self.client.get_item_price_and_stock(var_sku)
            var_price = pricing_info["price"]
            var_currency = pricing_info["currency"]
            var_stock = pricing_info["stock_quantity"]

            # Image resolution
            raw_img = var.get("image") or parent_image
            var_image_url = None
            if raw_img:
                var_image_url = (
                    raw_img
                    if raw_img.startswith("http")
                    else f"{self.client.base_url}/{raw_img.lstrip('/')}"
                )

            # Product URL: use parent route if available
            var_product_url = (
                f"{self.client.base_url}/{parent_route.lstrip('/')}"
                if parent_route
                else f"{self.client.base_url}/products/{var_sku.lower()}"
            )

            # Build variant description (parent description + variant attributes)
            attr_summary = ", ".join(f"{k}: {v}" for k, v in var_attrs.items())
            if parent_desc and attr_summary:
                var_description = f"{parent_desc}\n\nVariant: {attr_summary}"
            elif parent_desc:
                var_description = parent_desc
            elif attr_summary:
                var_description = f"{var_name} ({attr_summary})"
            else:
                var_description = var_name

            # Compose attributes JSONB
            composed_attributes: dict[str, Any] = {
                "variant_of": template_item_code,
                "variant_attributes": var_attrs,
                "specifications": parent_specs,
                "stock_uom": var.get("stock_uom", "Nos"),
                "is_variant": True,
            }
            # Also merge top-level variant attributes for convenience (e.g. color, size)
            for k, v in var_attrs.items():
                composed_attributes[k.lower()] = v

            # Upsert into PostgreSQL
            stmt = select(Product).where(Product.sku == var_sku)
            existing = (await db.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.name = var_name
                existing.description = var_description
                existing.category = var_category
                existing.price = var_price
                existing.currency = var_currency
                existing.stock_quantity = var_stock
                existing.product_url = var_product_url
                existing.image_url = var_image_url
                existing.attributes = composed_attributes
                existing.is_active = True
                updated += 1
            else:
                new_product = Product(
                    id=uuid.uuid4(),
                    sku=var_sku,
                    name=var_name,
                    description=var_description,
                    category=var_category,
                    price=var_price,
                    currency=var_currency,
                    stock_quantity=var_stock,
                    is_active=True,
                    product_url=var_product_url,
                    image_url=var_image_url,
                    attributes=composed_attributes,
                )
                db.add(new_product)
                created += 1

        return created, updated

sync_service = SyncService()