import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypedDict
from uuid import uuid4

import psycopg
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import get_settings


@dataclass(frozen=True)
class PostgresHarnessDatabase:
    async_url: str
    migration_url: str
    database_name: str


class PostgresConnectKwargs(TypedDict):
    host: str | None
    port: int | None
    dbname: str
    user: str | None
    password: str | None


def database_url(url: str, database_name: str) -> str:
    return make_url(url).set(database=database_name).render_as_string(hide_password=False)


def postgres_connect_kwargs(database_name: str) -> PostgresConnectKwargs:
    url = make_url(get_settings().database_migration_url)
    return {
        "host": url.host,
        "port": url.port,
        "dbname": database_name,
        "user": url.username,
        "password": url.password,
    }


def run_migrations(migration_url: str, revision: str = "head") -> None:
    previous_migration_url = os.environ.get("DATABASE_MIGRATION_URL")
    os.environ["DATABASE_MIGRATION_URL"] = migration_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), revision)
    finally:
        if previous_migration_url is None:
            os.environ.pop("DATABASE_MIGRATION_URL", None)
        else:
            os.environ["DATABASE_MIGRATION_URL"] = previous_migration_url
        get_settings.cache_clear()


@contextmanager
def temporary_postgres_database(prefix: str = "ms_harness_") -> Iterator[PostgresHarnessDatabase]:
    settings = get_settings()
    database_name = f"{prefix}{uuid4().hex}"

    with psycopg.connect(autocommit=True, **postgres_connect_kwargs("postgres")) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    database = PostgresHarnessDatabase(
        async_url=database_url(settings.database_url, database_name),
        migration_url=database_url(settings.database_migration_url, database_name),
        database_name=database_name,
    )

    try:
        yield database
    finally:
        with psycopg.connect(autocommit=True, **postgres_connect_kwargs("postgres")) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()"
                    ),
                    (database_name,),
                )
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(database_name)
                    )
                )