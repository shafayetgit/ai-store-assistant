from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.config import settings
from app.core.database import engine, task_engine
from app.core.redis import close_redis_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown events."""
    # ━━ Startup Logic ━━
    print(f"🚀 Starting {settings.PROJECT_NAME} in {settings.ENVIRONMENT} mode...")
    yield
    # ━━ Shutdown Logic ━━
    print(f"🛑 Shutting down {settings.PROJECT_NAME}...")
    await close_redis_pool()
    await engine.dispose()
    await task_engine.dispose()