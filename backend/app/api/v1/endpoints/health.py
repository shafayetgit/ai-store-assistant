from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter()


@router.get("/health", summary="System Health & Connectivity Check")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
):
    """
    Verifies that FastAPI is running and actively connected to:
    - PostgreSQL (executes SELECT 1)
    - Redis (executes PING)
    """
    health_details = {
        "status": "healthy",
        "app_name": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "services": {
            "database": "unknown",
            "redis": "unknown",
        },
    }

    # 1. Check Database
    try:
        await db.execute(text("SELECT 1;"))
        health_details["services"]["database"] = "healthy"
    except Exception as e:
        health_details["services"]["database"] = f"unhealthy: {e!s}"
        health_details["status"] = "degraded"

    # 2. Check Redis
    try:
        pong = await redis_client.ping()
        health_details["services"]["redis"] = "healthy" if pong else "unhealthy"
    except Exception as e:
        health_details["services"]["redis"] = f"unhealthy: {e!s}"
        health_details["status"] = "degraded"

    http_status = (
        status.HTTP_200_OK
        if health_details["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return JSONResponse(status_code=http_status, content=health_details)