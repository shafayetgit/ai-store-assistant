import asyncio
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal as async_session_maker
from app.models.customer import Customer, ChannelIdentity
from app.models.product import Product
from app.models.order import Order, OrderItem, OrderStatus
from app.models.knowledge import KnowledgeDoc, KnowledgeChunk

async def seed_data():
    async with async_session_maker() as session:
        print("🌱 Seeding initial mock data into database...")

        # 0. Clean up any previous mock seed records for idempotency
        await session.execute(delete(KnowledgeDoc).where(KnowledgeDoc.title.in_([
            "Shipping & Delivery Policy",
            "Return, Refund & Exchange Policy",
            "Store Hours, Contact & Payment Options",
        ])))
        await session.execute(delete(OrderItem))
        await session.execute(delete(Order).where(Order.order_number == "SO-2026-0042"))
        await session.execute(delete(Product).where(Product.sku.in_([
            "TSH-BLK-001", "HOD-NVY-002", "EBD-PRO-003", "BOT-SLV-004", "SNK-WHT-005"
        ])))
        await session.execute(delete(ChannelIdentity).where(ChannelIdentity.channel_user_id.in_([
            "fb_psid_9876543210", "web_session_abc123xyz789"
        ])))
        await session.execute(delete(Customer).where(Customer.email.in_([
            "tanvir.ahmed@example.com", "nusrat.jahan@example.com"
        ])))
        await session.commit()

        # 1. Seed Customers & Channel Identities
        cust1 = Customer(
            full_name="Tanvir Ahmed",
            email="tanvir.ahmed@example.com",
            phone="+8801712345678",
            metadata_info={"vip": True, "city": "Dhaka"}
        )
        cust2 = Customer(
            full_name="Nusrat Jahan",
            email="nusrat.jahan@example.com",
            phone="+8801812345679",
            metadata_info={"vip": False, "city": "Chittagong"}
        )
        session.add_all([cust1, cust2])
        await session.flush()

        ident1 = ChannelIdentity(
            customer_id=cust1.id,
            channel_type="facebook",
            channel_user_id="fb_psid_9876543210",
            profile_data={"first_name": "Tanvir", "last_name": "Ahmed", "locale": "en_US"}
        )
        ident2 = ChannelIdentity(
            customer_id=cust2.id,
            channel_type="web",
            channel_user_id="web_session_abc123xyz789",
            profile_data={"browser": "Chrome", "ip": "103.205.10.5"}
        )
        session.add_all([ident1, ident2])

        # 2. Seed Products
        products = [
            Product(
                sku="TSH-BLK-001",
                name="Premium Crewneck Cotton T-Shirt (Black)",
                description="100% combed organic ring-spun cotton. Breathable, durable, and pre-shrunk.",
                price=Decimal("850.00"),
                currency="BDT",
                stock_quantity=45,
                is_active=True,
                category="Apparel",
                product_url="https://hnbpark.com/products/premium-crewneck-tshirt-black",
                image_url="https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=500",
                attributes={"sizes": ["S", "M", "L", "XL"], "color": "Black", "fabric": "100% Cotton"}
            ),
            Product(
                sku="HOD-NVY-002",
                name="Heavyweight Fleece Hoodie (Navy Blue)",
                description="Ultra-warm brushed fleece interior with double-lined hood and kangaroo pocket.",
                price=Decimal("2250.00"),
                currency="BDT",
                stock_quantity=18,
                is_active=True,
                category="Apparel",
                product_url="https://hnbpark.com/products/heavyweight-fleece-hoodie-navy",
                image_url="https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=500",
                attributes={"sizes": ["M", "L", "XL"], "color": "Navy Blue", "fabric": "Cotton/Polyester Blend"}
            ),
            Product(
                sku="EBD-PRO-003",
                name="AuraSound Wireless ANC Earbuds",
                description="Active Noise Cancellation, 32-hour total battery life, IPX5 water resistance, Bluetooth 5.3.",
                price=Decimal("3800.00"),
                currency="BDT",
                stock_quantity=12,
                is_active=True,
                category="Electronics",
                product_url="https://hnbpark.com/products/aurasound-wireless-earbuds",
                image_url="https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=500",
                attributes={"color": "Matte Black", "bluetooth": "5.3", "battery_hours": 32}
            ),
            Product(
                sku="BOT-SLV-004",
                name="Insulated Stainless Steel Water Bottle (750ml)",
                description="Double-wall vacuum insulation keeps drinks cold for 24 hours or hot for 12 hours. BPA free.",
                price=Decimal("1150.00"),
                currency="BDT",
                stock_quantity=30,
                is_active=True,
                category="Lifestyle",
                product_url="https://hnbpark.com/products/insulated-bottle-750ml",
                image_url="https://images.unsplash.com/photo-1602143407151-7111542de6e8?w=500",
                attributes={"capacity": "750ml", "material": "18/8 Stainless Steel", "color": "Silver"}
            ),
            Product(
                sku="SNK-WHT-005",
                name="Urban Glide Casual Sneakers (White)",
                description="Ergonomic memory-foam insole with flexible slip-resistant rubber outsole.",
                price=Decimal("3200.00"),
                currency="BDT",
                stock_quantity=0, # Out of stock to test inventory awareness!
                is_active=True,
                category="Footwear",
                product_url="https://hnbpark.com/products/urban-glide-sneakers-white",
                image_url="https://images.unsplash.com/photo-1549298916-b41d501d3772?w=500",
                attributes={"sizes": ["40", "41", "42", "43", "44"], "color": "White"}
            )
        ]
        session.add_all(products)
        await session.flush()

        # 3. Seed Orders & Items
        order1 = Order(
            order_number="SO-2026-0042",
            customer_id=cust1.id,
            status=OrderStatus.SHIPPED.value,
            tracking_code="PATHAO-88219-BD",
            total_amount=Decimal("3100.00"),
            currency="BDT",
            delivery_address="House 14, Road 5, Dhanmondi, Dhaka-1205",
            contact_phone="+8801712345678",
            contact_email="tanvir.ahmed@example.com",
            estimated_delivery=datetime.now(timezone.utc) + timedelta(days=1)
        )
        session.add(order1)
        await session.flush()

        item1 = OrderItem(
            order_id=order1.id,
            product_id=products[0].id,
            sku=products[0].sku,
            item_name=products[0].name,
            quantity=1,
            unit_price=Decimal("850.00"),
            total_price=Decimal("850.00"),
        )
        item2 = OrderItem(
            order_id=order1.id,
            product_id=products[1].id,
            sku=products[1].sku,
            item_name=products[1].name,
            quantity=1,
            unit_price=Decimal("2250.00"),
            total_price=Decimal("2250.00"),
        )
        session.add_all([item1, item2])

        # 4. Seed Knowledge Documents & Chunks
        doc_shipping = KnowledgeDoc(
            title="Shipping & Delivery Policy",
            category="shipping",
            source_url="https://hnbpark.com/policies/shipping"
        )
        doc_returns = KnowledgeDoc(
            title="Return, Refund & Exchange Policy",
            category="returns",
            source_url="https://hnbpark.com/policies/refund"
        )
        doc_hours = KnowledgeDoc(
            title="Store Hours, Contact & Payment Options",
            category="faq",
            source_url="https://hnbpark.com/contact"
        )
        session.add_all([doc_shipping, doc_returns, doc_hours])
        await session.flush()

        chunks = [
            KnowledgeChunk(
                doc_id=doc_shipping.id,
                title="Delivery Timelines and Charges in Bangladesh",
                content=(
                    "Inside Dhaka: Standard delivery takes 24 to 48 hours (Charge: 70 BDT). "
                    "Outside Dhaka: Delivery takes 2 to 4 business days via courier services like Pathao or Steadfast (Charge: 130 BDT). "
                    "Free shipping applies to all orders over 3,000 BDT."
                ),
                metadata_info={"category": "shipping", "keywords": ["delivery time", "shipping fee", "dhaka", "free shipping"]}
            ),
            KnowledgeChunk(
                doc_id=doc_returns.id,
                title="7-Day Return & Replacement Policy",
                content=(
                    "Customers may return or exchange unworn, unwashed items in original packaging within 7 days of receiving the package. "
                    "For damaged or incorrect items, we provide free pickup and instant replacement. "
                    "Refunds for cash on delivery orders are processed via bKash, Nagad, or bank transfer within 3 business days of item inspection."
                ),
                metadata_info={"category": "returns", "keywords": ["return", "exchange", "refund", "damaged item", "7 days"]}
            ),
            KnowledgeChunk(
                doc_id=doc_hours.id,
                title="Accepted Payment Methods & Customer Support Hours",
                content=(
                    "We accept Cash on Delivery (COD), bKash, Nagad, Rocket, and Visa/Mastercard credit/debit cards. "
                    "Our customer support team is available from 10:00 AM to 10:00 PM daily (Saturday to Friday). "
                    "For urgent queries, call our hotline at +880 9612-000000 or email support@hnbpark.com."
                ),
                metadata_info={"category": "payment", "keywords": ["payment methods", "cod", "bkash", "nagad", "support hours", "hotline"]}
            )
        ]
        session.add_all(chunks)
        await session.commit()

        # 5. Generate and Store Vector Embeddings for Knowledge Chunks
        try:
            from app.services.rag_service import rag_service
            embedded_count = await rag_service.embed_unembedded_chunks(session)
            print(f"  - Vector Embeddings: Embedded {embedded_count} chunks into pgvector")
        except Exception as emb_exc:
            print(f"  - Vector Embeddings: Skipped ({emb_exc}) — keyword fallback active")

        print("✅ Mock data seeded successfully!")
        print(f"  - Customers: 2")
        print(f"  - Products: {len(products)} (including 1 out-of-stock item)")
        print(f"  - Orders: 1 (with 2 items)")
        print(f"  - Knowledge Docs: 3 (with {len(chunks)} chunks)")

if __name__ == "__main__":
    asyncio.run(seed_data())