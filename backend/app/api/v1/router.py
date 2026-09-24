from fastapi import APIRouter
from app.api.v1.endpoints import health, webhook_messenger, webhook_frappe, chat, knowledge, products

api_v1_router = APIRouter()
api_v1_router.include_router(health.router, tags=["Health"])
api_v1_router.include_router(webhook_messenger.router, prefix="/webhooks", tags=["Webhook"])
api_v1_router.include_router(webhook_frappe.router, prefix="/webhooks", tags=["Frappe Webhook"])
api_v1_router.include_router(chat.router, prefix="/chat", tags=["Web Chat"])
api_v1_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base"])
api_v1_router.include_router(products.router, prefix="/products", tags=["Products"])