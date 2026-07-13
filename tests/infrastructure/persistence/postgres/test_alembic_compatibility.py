import psycopg
import pytest

from tests.infrastructure.persistence.postgres._harness import (
    postgres_connect_kwargs,
    run_migrations,
    temporary_postgres_database,
)

LATEST_REVISION = "0017_crm_sync_active_guard"


def test_migrations_upgrade_legacy_alembic_version_table() -> None:
    try:
        with temporary_postgres_database(prefix="ms_alembic_") as database:
            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "CREATE TABLE alembic_version "
                        "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                    )
                    assert _version_num_length(cursor) == 32

            run_migrations(database.migration_url)

            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    assert _version_num_length(cursor) == 255
                    cursor.execute("SELECT version_num FROM alembic_version")
                    assert cursor.fetchone() == (LATEST_REVISION,)
    except psycopg.OperationalError as error:
        pytest.skip(f"Local Postgres is unavailable for the migration compatibility test: {error}")


def _version_num_length(cursor: psycopg.Cursor[tuple[object]]) -> int:
    cursor.execute(
        """
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_name = 'alembic_version' AND column_name = 'version_num'
        """
    )
    row = cursor.fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, int)
    return value
