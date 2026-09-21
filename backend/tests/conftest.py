from collections.abc import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    """Disposes SQLAlchemy connection pool between tests to prevent cross-loop errors."""
    yield
    await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session for tool testing."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def client():
    """Provides an asynchronous test client for FastAPI endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac