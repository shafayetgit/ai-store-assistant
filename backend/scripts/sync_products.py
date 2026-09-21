import asyncio
import argparse
import sys
import os

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.services.sync_service import sync_service
from app.services.frappe_client import frappe_client

async def run_sync(limit: int = 100):
    print("=" * 65)
    print("📦 AI Store Assistant — Product Catalog Sync")
    print("=" * 65)
    print(f"🔗 Target Store URL : {frappe_client.base_url}")
    print(f"🔑 API Key Configured: {'Yes' if frappe_client.is_configured else 'No (Missing API Key/Secret)'}")
    print(f"📄 Fetch Limit       : {limit} items")
    print("-" * 65)

    if not frappe_client.is_configured:
        print("❌ Cannot sync products: STORE_API_KEY or STORE_API_SECRET is missing in .env")
        print("   Please configure them in backend/.env first.")
        return

    async with AsyncSessionLocal() as session:
        result = await sync_service.sync_catalog(db=session, limit=limit)
        
        print("\n📊 Sync Summary:")
        print(f"   Status        : {result.get('status')}")
        print(f"   Total Synced  : {result.get('total_synced', 0)}")
        print(f"   Newly Created : {result.get('created', 0)}")
        print(f"   Updated Items : {result.get('updated', 0)}")
        
        errors = result.get("errors", [])
        if errors:
            print(f"   ⚠️ Errors ({len(errors)}):")
            for err in errors[:5]:
                print(f"      - {err}")
        else:
            print("   ✅ No errors encountered!")
            
    print("=" * 65)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync products from ERPNext/Frappe into AI Store Assistant DB")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of items to sync (default: 100)")
    args = parser.parse_args()

    asyncio.run(run_sync(limit=args.limit))

