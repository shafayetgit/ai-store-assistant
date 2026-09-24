from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product
from app.services.sync_service import sync_service


@pytest.mark.asyncio
async def test_frappe_webhook_secret_auth(client: AsyncClient, monkeypatch):
    """Verifies that webhook secret authentication works via header and Bearer token."""
    monkeypatch.setattr(settings, "STORE_WEBHOOK_SECRET", "super_secret_webhook_key")

    payload = {"event": "on_update", "item_code": "TEST-SKU-AUTH"}

    # 1. Missing secret header -> 401
    res1 = await client.post("/api/v1/webhooks/frappe/product", json=payload)
    assert res1.status_code == 401

    # 2. Invalid secret header -> 401
    res2 = await client.post(
        "/api/v1/webhooks/frappe/product",
        json=payload,
        headers={"X-Frappe-Webhook-Secret": "wrong_key"},
    )
    assert res2.status_code == 401

    # 3. Valid X-Frappe-Webhook-Secret -> 200
    res3 = await client.post(
        "/api/v1/webhooks/frappe/product",
        json=payload,
        headers={"X-Frappe-Webhook-Secret": "super_secret_webhook_key"},
    )
    assert res3.status_code == 200
    assert res3.json()["status"] == "queued"
    assert res3.json()["sku"] == "TEST-SKU-AUTH"

    # 4. Valid Authorization: Bearer <secret> -> 200
    res4 = await client.post(
        "/api/v1/webhooks/frappe/product",
        json=payload,
        headers={"Authorization": "Bearer super_secret_webhook_key"},
    )
    assert res4.status_code == 200


@pytest.mark.asyncio
async def test_frappe_webhook_missing_sku(client: AsyncClient):
    """Verifies that requests without item_code or name return 400."""
    res = await client.post("/api/v1/webhooks/frappe/product", json={"event": "on_update"})
    assert res.status_code == 400
    assert "Missing 'item_code' or 'name'" in res.json()["detail"]


@pytest.mark.asyncio
async def test_frappe_webhook_nested_doc_sync(client: AsyncClient, db_session: AsyncSession):
    """Verifies nested doc payload creates or updates product in database."""
    test_sku = "TEST-HOOK-NESTED-01"

    # Clean up if existed
    existing = (await db_session.execute(select(Product).where(Product.sku == test_sku))).scalar_one_or_none()
    if existing:
        await db_session.delete(existing)
        await db_session.commit()

    # Direct sync call via sync_service
    doc_payload = {
        "item_code": test_sku,
        "item_name": "Super Fast Charger 65W",
        "description": "Gallium Nitride high speed multi-port charger",
        "standard_rate": 850.00,
        "item_group": "Electronics",
        "image": "/files/charger-65w.png",
    }

    result = await sync_service.sync_single_product(
        db=db_session,
        sku=test_sku,
        event="after_insert",
        doc_data=doc_payload,
    )
    assert result["status"] == "created"
    assert result["sku"] == test_sku

    # Check product in DB
    prod = (await db_session.execute(select(Product).where(Product.sku == test_sku))).scalar_one_or_none()
    assert prod is not None
    assert prod.name == "Super Fast Charger 65W"
    assert prod.price == Decimal("850.00")
    assert prod.category == "Electronics"
    assert prod.is_active is True
    assert prod.image_url.startswith("https://") or prod.image_url.startswith("http://")

    # Clean up
    await db_session.delete(prod)
    await db_session.commit()


@pytest.mark.asyncio
async def test_frappe_webhook_deactivation_on_trash_or_disabled(db_session: AsyncSession):
    """Verifies that on_trash or disabled=1 soft-deactivates the product."""
    test_sku = "TEST-HOOK-TRASH-01"

    # Create active product
    prod = Product(
        sku=test_sku,
        name="Temporary Protective Case",
        price=Decimal("150.00"),
        is_active=True,
    )
    db_session.add(prod)
    await db_session.commit()

    # 1. Test event="on_trash"
    res1 = await sync_service.sync_single_product(
        db=db_session,
        sku=test_sku,
        event="on_trash",
    )
    assert res1["status"] == "deactivated"

    await db_session.refresh(prod)
    assert prod.is_active is False

    # Reactivate
    prod.is_active = True
    await db_session.commit()

    # 2. Test doc_data={"disabled": 1}
    res2 = await sync_service.sync_single_product(
        db=db_session,
        sku=test_sku,
        event="on_update",
        doc_data={"disabled": 1},
    )
    assert res2["status"] == "deactivated"

    await db_session.refresh(prod)
    assert prod.is_active is False

    # Clean up
    await db_session.delete(prod)
    await db_session.commit()

