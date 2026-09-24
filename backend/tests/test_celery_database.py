import asyncio
import pytest
from sqlalchemy import text
from app.core.database import TaskSessionLocal


def test_task_session_local_across_separate_event_loops():
    """
    Verifies that TaskSessionLocal (backed by NullPool) safely works across
    separate, sequential asyncio event loops without raising
    'Task got Future attached to a different loop' or 'Event loop is closed'.
    This mirrors how Celery prefork workers execute sequential tasks.
    """
    async def query_db(iteration: int):
        async with TaskSessionLocal() as session:
            result = await session.execute(text(f"SELECT {iteration} AS val"))
            return result.scalar()

    # Loop 1
    val1 = asyncio.run(query_db(1))
    assert val1 == 1

    # Loop 2
    val2 = asyncio.run(query_db(2))
    assert val2 == 2

    # Loop 3
    val3 = asyncio.run(query_db(3))
    assert val3 == 3

