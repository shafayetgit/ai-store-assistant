import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.product import Product
from app.services.sync_service import sync_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ━━ Catalog Synchronization Endpoints ━━

@router.post(
    "/sync",
    summary="Batch sync product catalog from ERPNext into PostgreSQL",
)
async def sync_all_products(
    limit: int = Query(default=100, ge=1, le=500, description="Max number of items to pull from ERPNext"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Pulls published items from Frappe / ERPNext Webshop and upserts
    them into the local PostgreSQL products table.
    """
    try:
        result = await sync_service.sync_catalog(db=db, limit=limit)
        return result
    except Exception as exc:
        logger.error(f"Catalog batch sync failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync catalog from ERPNext: {exc}",
        )


@router.post(
    "/sync/{sku}",
    summary="Sync a single product by SKU from ERPNext",
)
async def sync_single_product_by_sku(
    sku: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Fetches the latest details, price, and stock for a specific SKU from ERPNext
    and upserts it into the local database.
    """
    clean_sku = sku.strip()
    if not clean_sku:
        raise HTTPException(status_code=400, detail="SKU cannot be empty.")

    try:
        result = await sync_service.sync_single_product(
            db=db,
            sku=clean_sku,
            event="on_update",
            doc_data={"item_code": clean_sku},
        )
        if result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=f"Product '{clean_sku}' not found in ERPNext.")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to sync product '{clean_sku}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync SKU '{clean_sku}': {exc}",
        )


# ━━ Catalog Query Endpoints ━━

@router.get(
    "",
    summary="List and search local store products",
)
async def list_products(
    query: str | None = Query(default=None, description="Keyword search in product name or description"),
    category: str | None = Query(default=None, description="Filter by category (e.g. 'Apparel', 'Electronics')"),
    in_stock_only: bool = Query(default=False, description="Filter only items currently in stock"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns stored products with optional keyword, category, and in-stock filtering.
    """
    stmt = select(Product).where(Product.is_active == True)

    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(pattern),
                Product.description.ilike(pattern),
                Product.sku.ilike(pattern),
            )
        )

    if category:
        stmt = stmt.where(Product.category.ilike(category.strip()))

    if in_stock_only:
        stmt = stmt.where(Product.stock_quantity > 0)

    # Count total matching
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0

    # Paged query
    stmt = stmt.order_by(Product.name.asc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "products": [
            {
                "id": str(p.id),
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price": float(p.price),
                "currency": p.currency,
                "stock_quantity": p.stock_quantity,
                "in_stock": p.stock_quantity > 0,
                "product_url": p.product_url,
                "image_url": p.image_url,
                "attributes": p.attributes or {},
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in rows
        ],
    }


@router.get(
    "/{sku}",
    summary="Get single product details by SKU",
)
async def get_product_by_sku(
    sku: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns full details for a product by its unique SKU / Item Code.
    """
    stmt = select(Product).where(Product.sku == sku.strip(), Product.is_active == True)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product with SKU '{sku}' not found.")

    return {
        "id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category": product.category,
        "price": float(product.price),
        "currency": product.currency,
        "stock_quantity": product.stock_quantity,
        "in_stock": product.stock_quantity > 0,
        "product_url": product.product_url,
        "image_url": product.image_url,
        "attributes": product.attributes or {},
    }