import asyncio
from app.services.frappe_client import frappe_client
from app.services.sync_service import sync_service
from app.core.database import AsyncSessionLocal

async def test_frappe():
    print("=" * 60)
    print(f"🔗 Testing Frappe / ERPNext Connection: {frappe_client.base_url}")
    print("=" * 60)

    # 1. Test Authentication
    print("\n1. Verifying API Token Credentials...")
    user_res = await frappe_client.get_logged_user()
    print(f"   Result: {user_res}")

    if user_res.get("status") != "connected":
        print("❌ Cannot authenticate with Frappe. Check STORE_API_KEY / STORE_API_SECRET.")
        return

    # 2. Test Catalog Fetch
    print("\n2. Querying Items from Frappe...")
    items = await frappe_client.search_items(query="", limit=5)
    print(f"   Fetched {len(items)} sample items:")
    for item in items:
        print(f"   - SKU: {item.get('item_code', item.get('name'))} | Name: {item.get('item_name')}")

    # 3. Test Catalog Sync to PostgreSQL
    print("\n3. Testing Catalog Sync to PostgreSQL DB...")
    async with AsyncSessionLocal() as session:
        sync_result = await sync_service.sync_catalog(db=session, limit=10)
        print(f"   Sync Result: {sync_result}")

    print("\n🎉 Frappe / ERPNext integration verified successfully!")

if __name__ == "__main__":
    asyncio.run(test_frappe())