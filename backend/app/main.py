from fastapi import FastAPI

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.middleware import setup_middleware


def create_application() -> FastAPI:
    """FastAPI Application Factory."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="AI-powered customer support and sales automation platform for online stores.",
        version="0.1.0",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=lifespan,
    )


    setup_middleware(app)
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    return app


app = create_application()