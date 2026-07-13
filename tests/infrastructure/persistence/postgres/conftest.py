from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import enable_postgres_service_access
from tests.infrastructure.persistence.postgres._harness import (
    PostgresHarnessDatabase,
    run_migrations,
    temporary_postgres_database,
)


@pytest.fixture(scope="session")
def postgres_harness_database() -> Iterator[PostgresHarnessDatabase]:
    try:
        with temporary_postgres_database() as database:
            run_migrations(database.migration_url)
            yield database
    except psycopg.OperationalError as error:
        pytest.skip(
            f"Local Postgres is unavailable for the real harness: {error.__class__.__name__}"
        )


@pytest_asyncio.fixture
async def postgres_session(
    postgres_harness_database: PostgresHarnessDatabase,
) -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = create_async_engine(
        postgres_harness_database.async_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await enable_postgres_service_access(session)
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
