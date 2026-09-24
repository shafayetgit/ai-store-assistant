from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


@pytest.fixture(autouse=True)
async def seed_test_products(db_session: AsyncSession):
    """Seeds test products before each test and cleans up after."""
    p1 = Product(
        sku="TEST-PROD-001",
        name="Wireless Ergonomic Mouse",
        description="2.4GHz high precision optical mouse with silent click.",
        price=Decimal("1250.00"),
        currency="BDT",
        stock_quantity=25,
        category="Electronics",
        is_active=True,
    )
    p2 = Product(
        sku="TEST-PROD-002",
        name="Mechanical Gaming Keyboard",
        description="RGB backlit mechanical keyboard with blue switches.",
        price=Decimal("3500.00"),
        currency="BDT",
        stock_quantity=0,  # Out of stock
        category="Electronics",
        is_active=True,
    )
    p3 = Product(
        sku="TEST-PROD-003",
        name="Canvas Tote Bag",
        description="Eco-friendly cotton tote bag for daily shopping.",
        price=Decimal("450.00"),
        currency="BDT",
        stock_quantity=15,
        category="Lifestyle",
        is_active=True,
    )
    db_session.add_all([p1, p2, p3])
    await db_session.commit()

    yield

    # Teardown
    stmt = select(Product).where(Product.sku.in_(["TEST-PROD-001", "TEST-PROD-002", "TEST-PROD-003"]))
    prods = (await db_session.execute(stmt)).scalars().all()
    for p in prods:
        await db_session.delete(p)
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_products_all(client: AsyncClient):
    """Verifies listing active products with default pagination."""
    res = await client.get("/api/v1/products")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 3
    assert len(data["products"]) >= 3


@pytest.mark.asyncio
async def test_list_products_with_filters(client: AsyncClient):
    """Verifies keyword, category, and in_stock_only filtering."""
    # 1. Search keyword "Mouse"
    res1 = await client.get("/api/v1/products?query=Mouse")
    assert res1.status_code == 200
    skus1 = [p["sku"] for p in res1.json()["products"]]
    assert "TEST-PROD-001" in skus1
    assert "TEST-PROD-002" not in skus1

    # 2. Filter category "Lifestyle"
    res2 = await client.get("/api/v1/products?category=Lifestyle")
    assert res2.status_code == 200
    skus2 = [p["sku"] for p in res2.json()["products"]]
    assert "TEST-PROD-003" in skus2
    assert "TEST-PROD-001" not in skus2

    # 3. Filter in_stock_only=true (TEST-PROD-002 is out of stock)
    res3 = await client.get("/api/v1/products?category=Electronics&in_stock_only=true")
    assert res3.status_code == 200
    skus3 = [p["sku"] for p in res3.json()["products"]]
    assert "TEST-PROD-001" in skus3
    assert "TEST-PROD-002" not in skus3


@pytest.mark.asyncio
async def test_get_product_by_sku(client: AsyncClient):
    """Verifies fetching single product details and 404 for unknown SKU."""
    # Existing product
    res = await client.get("/api/v1/products/TEST-PROD-001")
    assert res.status_code == 200
    prod = res.json()
    assert prod["sku"] == "TEST-PROD-001"
    assert prod["name"] == "Wireless Ergonomic Mouse"
    assert prod["price"] == 1250.00
    assert prod["in_stock"] is True

    # Non-existent product -> 404
    res_404 = await client.get("/api/v1/products/UNKNOWN-SKU-999")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_sync_single_product_endpoint(client: AsyncClient):
    """Verifies POST /api/v1/products/sync/{sku} triggers sync."""
    res = await client.post("/api/v1/products/sync/TEST-PROD-001")
    # In dev mode without live Frappe, sync_single_product upserts or updates
    assert res.status_code in (200, 404)
    data = res.json()
    assert "status" in data or "detail" in data