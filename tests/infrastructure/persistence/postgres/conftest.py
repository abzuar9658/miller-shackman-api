import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import TypedDict
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import get_settings


@dataclass(frozen=True)
class PostgresHarnessDatabase:
    async_url: str
    migration_url: str
    database_name: str


class AdminConnectKwargs(TypedDict):
    host: str | None
    port: int | None
    dbname: str
    user: str | None
    password: str | None


def _database_url(url: str, database_name: str) -> str:
    return make_url(url).set(database=database_name).render_as_string(hide_password=False)


def _admin_connect_kwargs() -> AdminConnectKwargs:
    url = make_url(get_settings().database_migration_url)
    return {
        "host": url.host,
        "port": url.port,
        "dbname": "postgres",
        "user": url.username,
        "password": url.password,
    }


def _run_migrations(migration_url: str) -> None:
    previous_migration_url = os.environ.get("DATABASE_MIGRATION_URL")
    os.environ["DATABASE_MIGRATION_URL"] = migration_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous_migration_url is None:
            os.environ.pop("DATABASE_MIGRATION_URL", None)
        else:
            os.environ["DATABASE_MIGRATION_URL"] = previous_migration_url
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def postgres_harness_database() -> Iterator[PostgresHarnessDatabase]:
    settings = get_settings()
    database_name = f"ms_harness_{uuid4().hex}"

    try:
        with psycopg.connect(autocommit=True, **_admin_connect_kwargs()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except psycopg.OperationalError as error:
        pytest.skip(
            f"Local Postgres is unavailable for the real harness: {error.__class__.__name__}"
        )

    database = PostgresHarnessDatabase(
        async_url=_database_url(settings.database_url, database_name),
        migration_url=_database_url(settings.database_migration_url, database_name),
        database_name=database_name,
    )

    try:
        _run_migrations(database.migration_url)
        yield database
    finally:
        with psycopg.connect(autocommit=True, **_admin_connect_kwargs()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()"
                    ),
                    (database_name,),
                )
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
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
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()